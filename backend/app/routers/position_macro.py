"""持仓评估和宏观风险分析API端点"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime, timedelta
import asyncio
import time

from app.schemas.position_assessment import (
    PositionsAssessmentResponse,
    TechnicalAnalysisResponse,
    FundamentalAnalysisResponse
)
from app.schemas.macro_risk import MacroRiskOverviewResponse
from app.services.technical_analysis_service import TechnicalAnalysisService
from app.services.fundamental_analysis_service import FundamentalAnalysisService
from app.services.position_scoring_service import PositionScoringService
from app.services.trading_plan_service import TradingPlanService
from app.core.config import settings
from app.services.macro_indicators_service import MacroIndicatorsService
from app.services.macro_risk_scoring_service import MacroRiskScoringService
from app.services.geopolitical_events_service import GeopoliticalEventsService
from app.services.ai_analysis_service import AIAnalysisService
from app.broker.factory import make_option_broker_client
from app.providers.market_data_provider import MarketDataProvider
from app.core.cache import cache
from app.core.config import settings
from app.models.db import SessionLocal
from app.jobs.scheduler import add_job

router = APIRouter()


# 依赖项：数据库会话（延迟导入避免循环依赖）
async def get_session():
    from app.models.db import SessionLocal
    async with SessionLocal() as session:
        yield session


@router.get("/positions/assessment", response_model=PositionsAssessmentResponse)
async def get_positions_assessment(
    window_days: int = Query(7, description="窗口期（天）"),
    force_refresh: bool = Query(False, description="是否强制刷新缓存与快照"),
    session: AsyncSession = Depends(get_session)
):
    """获取持仓评估
    
    返回当前持仓的综合评估，包括：
    - 技术面、基本面、情绪面评分
    - 持仓建议（买入/持有/减仓/卖出）
    - 风险预警
    - 组合总结
    """
    try:
        # 获取当前持仓（同时获取股票和期权）
        trade_client = make_option_broker_client()
        account_id = await trade_client.get_account_id()

        # 短TTL缓存（避免高频重复计算）
        cache_key = f"positions_assessment:{account_id}:{window_days}"
        if not force_refresh:
            cached_assessment = await cache.get(cache_key)
            if cached_assessment:
                return cached_assessment
        
        # 获取股票持仓
        stock_positions = await trade_client.list_underlying_positions(account_id)
        
        # 获取期权持仓（无期权行情权限时降级为无期权）
        try:
            option_positions = await trade_client.list_option_positions(account_id)
        except Exception as e:
            print(f"[PositionAssessment] Option positions unavailable, fallback to empty. reason={e}")
            option_positions = []
        
        # 按标的分组期权持仓
        option_by_underlying = {}
        if option_positions:
            for opt_pos in option_positions:
                underlying = opt_pos.contract.underlying
                if underlying not in option_by_underlying:
                    option_by_underlying[underlying] = []
                option_by_underlying[underlying].append(opt_pos)
        
        # 合并股票和期权持仓的标的列表（去重）
        all_symbols = set([p.symbol for p in stock_positions])
        all_symbols.update(option_by_underlying.keys())
        
        if not all_symbols:
            return PositionsAssessmentResponse(
                positions=[],
                summary={
                    "total_positions": 0,
                    "total_value": 0.0,
                    "total_pnl": 0.0,
                    "avg_score": 0.0,
                    "high_risk_count": 0,
                    "buy_recommendation_count": 0
                }
            )
        
        # 提取股票代码列表
        symbols = list(all_symbols)
        
        # 批量计算评分
        scoring_service = PositionScoringService()
        scores = await scoring_service.get_all_position_scores(symbols, force_refresh=force_refresh)
        technical_service = TechnicalAnalysisService(session)

        # 读取激活计划（用于偏离度计算）
        plan_service = TradingPlanService(session)
        plan_map = await plan_service.get_active_plans_by_symbols(account_id, symbols)

        # 获取风险预算（使用全局限额作为近似）
        budget_base = settings.DEFAULT_RISK_BUDGET_USD if hasattr(settings, "DEFAULT_RISK_BUDGET_USD") else 0
        if budget_base <= 0:
            budget_base = 20000.0
        
        # 构建响应
        position_assessments = []
        total_score = 0.0
        total_market_value = 0.0
        total_pnl = 0.0
        high_risk_count = 0
        buy_count = 0
        
        # 遍历所有标的
        for symbol in symbols:
            score_data = scores.get(symbol)
            
            # 查找该标的的股票持仓
            stock_position = next((p for p in stock_positions if p.symbol == symbol), None)
            
            # 查找该标的的期权持仓
            symbol_options = option_by_underlying.get(symbol, [])
            
            # 计算股票部分
            stock_quantity = 0
            stock_avg_cost = 0.0
            stock_last_price = 0.0
            stock_market_value = 0.0
            stock_pnl = 0.0
            
            if stock_position:
                stock_quantity = stock_position.quantity
                stock_avg_cost = stock_position.avg_price if stock_position.avg_price else 0.0
                stock_last_price = stock_position.last_price if stock_position.last_price else stock_avg_cost
                stock_market_value = stock_quantity * stock_last_price
                stock_pnl = (stock_last_price - stock_avg_cost) * stock_quantity if stock_avg_cost > 0 else 0.0
            
            # 计算期权部分
            option_market_value = 0.0
            option_pnl = 0.0
            option_details = []
            
            if symbol_options:
                for opt_pos in symbol_options:
                    contract = opt_pos.contract
                    quantity = opt_pos.quantity
                    avg_price = opt_pos.avg_price
                    last_price = opt_pos.last_price
                    underlying_price = opt_pos.underlying_price
                    
                    # 计算期权市值和盈亏
                    # 市值 = 当前权利金价格 * 数量 * 乘数
                    # 盈亏 = (当前价格 - 成本价格) * 数量 * 乘数
                    # 如果 quantity 为负（卖出开仓），公式依旧适用：(last - avg) * (-qty) * mult
                    mkt_val = abs(quantity) * last_price * contract.multiplier
                    pnl = (last_price - avg_price) * quantity * contract.multiplier
                    
                    option_market_value += mkt_val
                    option_pnl += pnl
                    
                    # 记录期权详情
                    option_details.append({
                        "contract_symbol": contract.broker_symbol,
                        "right": contract.right,
                        "strike": contract.strike,
                        "expiry": contract.expiry.isoformat(),
                        "quantity": quantity,
                        "avg_price": avg_price,
                        "last_price": last_price,
                        "multiplier": contract.multiplier,
                        "unrealized_pnl": round(pnl, 2)
                    })
            
            # 获取当前价格（优先使用股票价格，否则使用期权的标的价格）
            if stock_last_price > 0:
                current_price = stock_last_price
            elif symbol_options and len(symbol_options) > 0:
                current_price = symbol_options[0].underlying_price
            else:
                print(f"[PositionAssessment] Skipping {symbol}: no price available")
                continue
            
            # 计算综合市值和盈亏
            total_symbol_market_value = stock_market_value + option_market_value
            total_symbol_pnl = stock_pnl + option_pnl
            
            # 如果有股票持仓，计算盈亏百分比
            if stock_avg_cost > 0 and stock_quantity > 0:
                unrealized_pnl_percent = ((current_price - stock_avg_cost) / stock_avg_cost * 100)
            else:
                unrealized_pnl_percent = 0.0
            
            # 获取趋势快照：优先获取今日快照
            snapshot = await technical_service.get_latest_trend_snapshot(
                symbol,
                account_id=account_id,
                timeframe="1D",
                only_today=True
            )
            
            # 如果没有今日快照，且触发了强制刷新，则尝试生成
            if not snapshot and force_refresh:
                try:
                    await technical_service.get_technical_analysis(
                        symbol,
                        timeframe="1D",
                        use_cache=False,
                        account_id=account_id
                    )
                    # 重新获取快照
                    snapshot = await technical_service.get_latest_trend_snapshot(
                        symbol,
                        account_id=account_id,
                        timeframe="1D",
                        only_today=True
                    )
                except Exception as e:
                    print(f"[PositionAssessment] Error generating snapshot for {symbol}: {e}")
                    # 记录错误，后续会自动尝试获取历史数据作为兜底
            
            # 关键优化：如果依然没有今日快照（生成失败或未开启强制刷新），则回退到历史最近的一次记录作为“降级展示”
            if not snapshot:
                snapshot = await technical_service.get_latest_trend_snapshot(
                    symbol,
                    account_id=account_id,
                    timeframe="1D",
                    only_today=False
                )
                if snapshot:
                    print(f"[PositionAssessment] Found historical snapshot for {symbol}, using as fallback.")
            
            # 处理最终依然为空的情况
            if not snapshot:
                # 保底逻辑（保持原有行为）
                error_desc = "数据尚未生成"
                ai_summary = f"{symbol} 快照尚未生成，可稍后重试或调用 /api/v1/positions/refresh。"
                
                snapshot = type('obj', (object,), {
                    'to_dict': lambda self: {
                        "symbol": symbol,
                        "timeframe": "1D",
                        "trend_direction": "INSUFFICIENT_DATA",
                        "trend_strength": 0,
                        "trend_description": error_desc,
                        "rsi_value": None,
                        "rsi_status": "INSUFFICIENT_DATA",
                        "macd_status": "INSUFFICIENT_DATA",
                        "macd_signal": None,
                        "bollinger_position": "INSUFFICIENT_DATA",
                        "volume_ratio": None,
                        "support_levels": [],
                        "resistance_levels": [],
                        "ai_summary": ai_summary,
                        "timestamp": datetime.now().isoformat()
                    }
                })()
            
            trend_snapshot = snapshot.to_dict() if snapshot else None

            # 对于港股，优先使用股票名称
            display_symbol = symbol
            if stock_position and stock_position.market == "HK" and stock_position.name:
                display_symbol = stock_position.name
            
            # 构建持仓评估数据（即使没有评分也显示基本信息）
            # 计划偏离度
            plan_deviation = None
            plan = plan_map.get(symbol)
            if plan and plan.entry_price:
                try:
                    plan_deviation = min(abs(current_price - float(plan.entry_price)) / float(plan.entry_price) * 100, 100)
                except Exception:
                    plan_deviation = None

            # 风险预算占用率（近似：使用市值/预算）
            budget_utilization = round(min(total_symbol_market_value / max(budget_base, 1e-6), 1.0), 4)

            # 获取行业属性（从 score_data 中提取，用于前端显示）
            sector = getattr(score_data, 'sector', "Unknown") or "Unknown"
            industry = getattr(score_data, 'industry', "Unknown") or "Unknown"
            beta = getattr(score_data, 'beta', 1.0) or 1.0

            assessment = {
                "symbol": display_symbol,
                "ticker": symbol,  # 始终保存原始代码
                "quantity": stock_quantity,
                "avg_cost": stock_avg_cost,
                "current_price": current_price,
                "market_value": round(total_symbol_market_value, 2),
                "unrealized_pnl": round(total_symbol_pnl, 2),
                "unrealized_pnl_percent": round(unrealized_pnl_percent, 2),
                "budget_utilization": budget_utilization,
                "plan_deviation": plan_deviation,
                "sector": sector,
                "industry": industry,
                "beta": beta,
                # 评分数据（使用默认值如果不可用）
                "overall_score": score_data.overall_score if score_data else 50,
                "technical_score": score_data.technical_score if score_data else 50,
                "fundamental_score": score_data.fundamental_score if score_data else 50,
                "sentiment_score": score_data.sentiment_score if score_data else 50,
                "risk_level": score_data.risk_level if score_data else "MEDIUM",
                "recommendation": score_data.recommendation if score_data else "HOLD",
                "target_position": score_data.target_position if score_data else 0.5,
                "stop_loss": score_data.stop_loss if score_data else current_price * 0.9,
                "take_profit": score_data.take_profit if score_data else current_price * 1.1,
                "trend_snapshot": trend_snapshot
            }
            
            # 如果有期权持仓，添加期权详情
            if option_details:
                assessment["option_positions"] = option_details
            
            position_assessments.append(assessment)
            
            # 累加总计数据
            total_market_value += total_symbol_market_value
            total_pnl += total_symbol_pnl
            
            # 统计数据
            score_value = score_data.overall_score if score_data else 50
            total_score += score_value
            
            risk = score_data.risk_level if score_data else "MEDIUM"
            if risk in ["HIGH", "EXTREME"]:
                high_risk_count += 1
                
            rec = score_data.recommendation if score_data else "HOLD"
            if rec in ["BUY", "STRONG_BUY"]:
                buy_count += 1

        # 新增：组合维度指标计算
        portfolio_weighted_score = 0.0
        portfolio_weighted_beta = 0.0
        sector_distribution = {}
        industry_distribution = {}

        for p in position_assessments:
            weight = p["market_value"] / max(total_market_value, 1.0)
            portfolio_weighted_score += (p["overall_score"] * weight)
            
            # 尝试从 scores 获取行业和 beta 信息，若无则使用默认值
            s_data = scores.get(p["ticker"])
            beta = 1.0
            sector = "Unknown"
            industry = "Unknown"

            if s_data:
                beta = getattr(s_data, 'beta', 1.0) or 1.0
                sector = getattr(s_data, 'sector', "Unknown") or "Unknown"
                industry = getattr(s_data, 'industry', "Unknown") or "Unknown"
            
            portfolio_weighted_beta += (beta * weight)
            sector_distribution[sector] = sector_distribution.get(sector, 0.0) + p["market_value"]
            industry_distribution[industry] = industry_distribution.get(industry, 0.0) + p["market_value"]

        # 转换为占比
        portfolio_sector_ratios = {k: round(v / max(total_market_value, 1.0), 4) for k, v in sector_distribution.items()}
        portfolio_industry_ratios = {k: round(v / max(total_market_value, 1.0), 4) for k, v in industry_distribution.items()}

        # 准备 AI 组合建议
        ai_recommendations = []
        portfolio_analysis = {
            "weighted_score": round(portfolio_weighted_score, 2),
            "total_beta": round(portfolio_weighted_beta, 2),
            "sector_ratios": portfolio_sector_ratios,
            "industry_ratios": portfolio_industry_ratios
        }

        try:
            ai_service = AIAnalysisService()
            # 获取 AI 组合分析
            portfolio_ai = await ai_service.generate_portfolio_assessment(
                avg_score=portfolio_weighted_score,
                total_beta=portfolio_weighted_beta,
                sector_distribution=portfolio_sector_ratios,
                position_count=len(position_assessments)
            )
            if portfolio_ai:
                portfolio_analysis["ai_summary"] = portfolio_ai.get("summary")
                ai_recommendations = portfolio_ai.get("recommendations", [])
        except Exception as e:
            print(f"[PositionAssessment] AI Portfolio analysis failed: {e}")

        avg_score = total_score / len(position_assessments) if position_assessments else 0.0
        
        response = PositionsAssessmentResponse(
            positions=position_assessments,
            summary={
                "total_positions": len(position_assessments),
                "total_value": round(total_market_value, 2),
                "total_pnl": round(total_pnl, 2),
                "avg_score": round(avg_score, 2),
                "high_risk_count": high_risk_count,
                "buy_recommendation_count": buy_count
            },
            portfolio_analysis=portfolio_analysis,
            ai_recommendations=ai_recommendations
        )

        # 写入缓存（30秒）
        try:
            payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()
            await cache.set(cache_key, payload, expire=30)
        except Exception:
            pass

        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions assessment: {str(e)}")


@router.get("/positions/{symbol}/technical", response_model=TechnicalAnalysisResponse)
async def get_technical_analysis(
    symbol: str,
    timeframe: str = Query("1D", description="时间框架"),
    force_refresh: bool = Query(False, description="是否强制刷新"),
    session: AsyncSession = Depends(get_session)
):
    """获取技术分析
    
    返回标的的详细技术分析，包括：
    - 趋势方向和强度
    - RSI/MACD/布林带等技术指标
    - 支撑位和阻力位
    - AI技术面总结
    """
    try:
        service = TechnicalAnalysisService(session)

        # 使用真实账户ID写入/读取趋势快照，避免与 assessment 端点（真实 account_id）不一致
        trade_client = make_option_broker_client()
        account_id = await trade_client.get_account_id()
        technical_data = await service.get_technical_analysis(
            symbol,
            timeframe=timeframe,
            use_cache=not force_refresh,
            account_id=account_id
        )
        
        if not technical_data:
            raise HTTPException(status_code=404, detail=f"Technical data not found for {symbol}")
        
        # 生成AI摘要（可选）
        ai_summary = None
        try:
            ai_service = AIAnalysisService()
            # 构造技术数据字典
            tech_dict = {
                "trend": {
                    "trend_direction": technical_data.trend_direction,
                    "trend_strength": technical_data.trend_strength
                },
                "momentum": {
                    "rsi": {
                        "value": technical_data.rsi.value,
                        "status": technical_data.rsi.status,
                        "signal": technical_data.rsi.signal
                    },
                    "macd": {
                        "value": technical_data.macd.value,
                        "signal_line": technical_data.macd.signal_line,
                        "histogram": technical_data.macd.histogram,
                        "status": technical_data.macd.status
                    }
                },
                "support_resistance": {
                    "support": technical_data.support_levels,
                    "resistance": technical_data.resistance_levels
                }
            }
            ai_summary = await ai_service.generate_technical_summary(symbol, tech_dict)
        except Exception as e:
            # AI摘要失败不影响主流程
            pass
        
        return TechnicalAnalysisResponse(
            symbol=symbol,
            timeframe=timeframe,
            trend_direction=technical_data.trend_direction,
            trend_strength=technical_data.trend_strength,
            rsi=technical_data.rsi.value,
            macd=technical_data.macd.value,
            macd_signal=technical_data.macd.signal_line,
            bollinger_upper=technical_data.bollinger_bands.upper,
            bollinger_lower=technical_data.bollinger_bands.lower,
            support=technical_data.support_levels,
            resistance=technical_data.resistance_levels,
            volume_ratio=technical_data.volume_ratio,
            overall_score=float(technical_data.trend_strength),
            ai_summary=ai_summary,
            timestamp=technical_data.timestamp
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching technical analysis: {str(e)}")


@router.get("/positions/{symbol}/fundamental", response_model=FundamentalAnalysisResponse)
async def get_fundamental_analysis(
    symbol: str,
    force_refresh: bool = Query(False, description="是否强制刷新"),
    session: AsyncSession = Depends(get_session)
):
    """获取基本面分析
    
    返回标的的详细基本面分析，包括：
    - 估值水平（PE/PB/PS等）
    - 盈利能力（ROE/毛利率等）
    - 成长性（营收/利润增长率）
    - 财务健康度
    - 分析师评级
    - AI基本面总结
    """
    try:
        service = FundamentalAnalysisService()
        fundamental_data = await service.get_fundamental_data(symbol, force_refresh)
        
        if not fundamental_data:
            raise HTTPException(status_code=404, detail=f"Fundamental data not found for {symbol}")
        
        # \u751f\u6210AI\u6458\u8981\uff08\u53ef\u9009\uff09
        ai_summary = None
        try:
            ai_service = AIAnalysisService()
            # \u6784\u9020\u57fa\u672c\u9762\u6570\u636e\u5b57\u5178
            fund_dict = {
                "valuation": {
                    "pe_ratio": fundamental_data.pe_ratio,
                    "pb_ratio": fundamental_data.pb_ratio,
                    "peg_ratio": fundamental_data.peg_ratio,
                    "score": fundamental_data.valuation_score
                },
                "profitability": {
                    "roe": fundamental_data.roe,
                    "roa": fundamental_data.roa,
                    "profit_margin": fundamental_data.profit_margin,
                    "score": fundamental_data.profitability_score
                },
                "growth": {
                    "revenue_growth": fundamental_data.revenue_growth,
                    "earnings_growth": fundamental_data.earnings_growth,
                    "score": fundamental_data.growth_score
                },
                "financial_health": {
                    "quick_ratio": fundamental_data.current_ratio,
                    "debt_to_equity": fundamental_data.debt_to_equity,
                    "score": fundamental_data.health_score
                }
            }
            ai_summary = await ai_service.generate_fundamental_summary(symbol, fund_dict)
        except Exception as e:
            # AI\u6458\u8981\u5931\u8d25\u4e0d\u5f71\u54cd\u4e3b\u6d41\u7a0b
            pass
        
        return FundamentalAnalysisResponse(
            symbol=symbol,
            valuation={
                "pe_ratio": fundamental_data.pe_ratio,
                "pb_ratio": fundamental_data.pb_ratio,
                "peg_ratio": fundamental_data.peg_ratio,
                "score": fundamental_data.valuation_score
            },
            profitability={
                "roe": fundamental_data.roe,
                "roa": fundamental_data.roa,
                "profit_margin": fundamental_data.profit_margin,
                "score": fundamental_data.profitability_score
            },
            growth={
                "revenue_growth": fundamental_data.revenue_growth,
                "earnings_growth": fundamental_data.earnings_growth,
                "score": fundamental_data.growth_score
            },
            health={
                "current_ratio": fundamental_data.current_ratio,
                "debt_to_equity": fundamental_data.debt_to_equity,
                "score": fundamental_data.health_score
            },
            overall_score=fundamental_data.overall_score,
            ai_summary=ai_summary,
            timestamp=fundamental_data.timestamp
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching fundamental analysis: {str(e)}")


@router.post("/positions/refresh")
async def refresh_positions_assessment(
    symbols: Optional[List[str]] = None,
    force: bool = False,
    async_run: bool = Query(False, description="是否异步执行"),
    session: AsyncSession = Depends(get_session)
):
    """刷新持仓评估
    
    重新计算指定标的的评分和分析。
    如果不指定symbols，则刷新所有持仓。
    """
    try:
        # 如果未指定symbols，获取所有持仓
        if not symbols:
            trade_client = make_option_broker_client()
            account_id = await trade_client.get_account_id()
            positions = await trade_client.list_underlying_positions(account_id)
            symbols = [p.symbol for p in positions]
        else:
            trade_client = make_option_broker_client()
            account_id = await trade_client.get_account_id()
        
        if not symbols:
            return {"message": "No positions to refresh", "refreshed": []}
        
        async def _do_refresh(run_symbols: List[str], run_account_id: str, run_force: bool):
            sem = asyncio.Semaphore(settings.REFRESH_CONCURRENCY)

            # 先判断哪些标的确实需要刷新（节省不必要的API/DB开销）
            to_refresh_tech: List[str] = []
            for s in run_symbols:
                async with SessionLocal() as tmp_sess:
                    tech_check = TechnicalAnalysisService(tmp_sess)
                    try:
                        need = await tech_check.needs_refresh(s, timeframe="1D", force=run_force)
                    except Exception:
                        need = True
                    if need:
                        to_refresh_tech.append(s)

            async def _refresh_technical(sym: str) -> tuple[str, Optional[object]]:
                async with sem:
                    start = time.time()
                    try:
                        async with SessionLocal() as local_session:
                            technical_service = TechnicalAnalysisService(local_session)
                            # 禁用AI以避免长尾延迟；预计算并写入快照（内部会commit）
                            data = await technical_service.get_technical_analysis(
                                sym,
                                timeframe="1D",
                                use_cache=False,
                                account_id=run_account_id,
                                use_ai=False
                            )
                        elapsed = int((time.time() - start) * 1000)
                        await cache.set(f"positions_refresh:timing:{run_account_id}:{sym}", {"technical_ms": elapsed, "timestamp": datetime.now().isoformat()}, expire=3600)
                        return sym, data
                    except Exception as e:
                        print(f"Error refreshing technical for {sym}: {e}")
                        await cache.set(f"positions_refresh:timing:{run_account_id}:{sym}", {"technical_ms": -1, "error": str(e), "timestamp": datetime.now().isoformat()}, expire=3600)
                        return sym, None

            async def _refresh_score(sym: str) -> tuple[str, bool]:
                async with sem:
                    start = time.time()
                    try:
                        current_price = await market_provider.get_current_price(sym)
                        tech_data = technical_results.get(sym) if 'technical_results' in locals() else None
                        score_obj = await scoring_service.calculate_position_score(
                            sym,
                            current_price=current_price,
                            force_refresh=run_force,
                            technical_data=tech_data
                        )
                        elapsed = int((time.time() - start) * 1000)
                        existing = await cache.get(f"positions_refresh:timing:{run_account_id}:{sym}") or {}
                        existing.update({"score_ms": elapsed})
                        await cache.set(f"positions_refresh:timing:{run_account_id}:{sym}", existing, expire=3600)
                        return sym, score_obj is not None
                    except Exception as e:
                        print(f"Error refreshing score for {sym}: {e}")
                        existing = await cache.get(f"positions_refresh:timing:{run_account_id}:{sym}") or {}
                        existing.update({"score_ms": -1, "error_score": str(e)})
                        await cache.set(f"positions_refresh:timing:{run_account_id}:{sym}", existing, expire=3600)
                        return sym, False

            # 并发刷新技术面（仅刷新需要的标的）
            technical_tasks = [_refresh_technical(sym) for sym in to_refresh_tech]
            technical_pairs = await asyncio.gather(*technical_tasks) if technical_tasks else []
            technical_results = {k: v for k, v in technical_pairs}

            # 并发刷新基本面（已并发实现）
            fundamental_service = FundamentalAnalysisService()
            fundamental_results = await fundamental_service.batch_refresh_fundamentals(run_symbols)

            # 并发刷新评分（传入预计算的技术数据以避免重复计算）
            score_tasks = [_refresh_score(sym) for sym in run_symbols]
            score_results = dict(await asyncio.gather(*score_tasks)) if score_tasks else {}

            # 标准化返回（technical -> bool success mapping）
            technical_bool_map = {k: (v is not None) for k, v in technical_results.items()}

            return {
                "technical": technical_bool_map,
                "fundamental": fundamental_results,
                "scores": score_results,
            }

        scoring_service = PositionScoringService()
        market_provider = MarketDataProvider()

        if async_run:
            if not settings.ENABLE_SCHEDULER:
                raise HTTPException(status_code=400, detail="Scheduler disabled, cannot run async job")
            job_id = f"positions_refresh:{account_id}:{int(time.time())}"
            add_job(
                _do_refresh,
                trigger="date",
                id=job_id,
                name="positions_refresh",
                run_date=datetime.now(),
                args=[symbols, account_id, force],
            )
            return {
                "status": "scheduled",
                "job_id": job_id,
                "refreshed": symbols,
            }

        results = await _do_refresh(symbols, account_id, force)
        
        return {
            "message": "Refresh completed",
            "refreshed": symbols,
            "results": {
                "technical": results["technical"],
                "fundamental": results["fundamental"],
                "scores": results["scores"]
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing positions: {str(e)}")


@router.get("/macro/risk/overview")
async def get_macro_risk_overview(
    force_refresh: bool = Query(False, description="是否强制刷新"),
    session: AsyncSession = Depends(get_session)
):
    """获取宏观风险概览（性能优化版）
    
    返回宏观环境的综合风险评估。
    
    性能优化措施：
    - 优先使用24小时缓存
    - 并行处理独立操作（风险计算、预警、事件）
    - AI分析15秒超时控制
    - 响应时间监控
    """
    try:
        cache_key = "macro_risk_overview"
        if not force_refresh:
            cached_overview = await cache.get(cache_key)
            if cached_overview:
                return cached_overview

        start_time = time.time()
        
        # 1. 优先计算或获取缓存的风险评分
        risk_service = MacroRiskScoringService()
        risk_score = await risk_service.calculate_macro_risk_score(use_cache=not force_refresh)
        
        # 2. 并行执行独立操作：风险预警 + 地缘事件
        alerts_task = asyncio.create_task(risk_service.generate_risk_alerts())
        
        geo_service = GeopoliticalEventsService()
        events_task = asyncio.create_task(geo_service.fetch_recent_events(days=7))
        
        # 等待并行任务完成
        alerts, recent_events = await asyncio.gather(
            alerts_task,
            events_task,
            return_exceptions=True
        )
        
        # 处理异常结果
        if isinstance(alerts, Exception):
            alerts = []
        if isinstance(recent_events, Exception):
            recent_events = []
        
        # 3. 构建基础响应数据
        response_data = {
            "timestamp": risk_score.timestamp,
            "overall_risk": {
                "score": risk_score.overall_score,
                "level": risk_score.risk_level,
                "summary": risk_score.risk_summary,
                "confidence": risk_score.confidence
            },
            "risk_breakdown": {
                "monetary_policy": {
                    "score": risk_score.monetary_policy_score,
                    "description": "货币政策风险评估"
                },
                "geopolitical": {
                    "score": risk_score.geopolitical_score,
                    "description": "地缘政治风险评估"
                },
                "sector_bubble": {
                    "score": risk_score.sector_bubble_score,
                    "description": "行业泡沫风险评估"
                },
                "economic_cycle": {
                    "score": risk_score.economic_cycle_score,
                    "description": "经济周期风险评估"
                },
                "market_sentiment": {
                    "score": risk_score.sentiment_score,
                    "description": "市场情绪风险评估"
                }
            },
            "alerts": alerts,
            "key_concerns": risk_score.key_concerns,
            "recommendations": risk_score.recommendations,
            "ai_analysis": risk_score.risk_summary,  # 默认使用风险摘要
            "recent_events": [
                {
                    "title": event.title,
                    "date": event.event_date.strftime("%Y-%m-%d"),
                    "category": event.category,
                    "severity": event.severity,
                    "impact_score": event.market_impact_score
                }
                for event in recent_events[:5] if hasattr(event, 'title')
            ]
        }
        
        # 4. 异步生成AI分析（带超时控制）
        try:
            async def generate_ai_with_timeout():
                ai_service = AIAnalysisService()
                macro_dict = {
                    "overall_risk": response_data["overall_risk"],
                    "risk_breakdown": response_data["risk_breakdown"],
                    "alerts": alerts,
                    "recent_events": recent_events[:5]
                }
                return await ai_service.generate_macro_analysis(macro_dict)
            
            # 15秒超时限制
            ai_analysis = await asyncio.wait_for(
                generate_ai_with_timeout(),
                timeout=15.0
            )
            if ai_analysis:
                response_data["ai_analysis"] = ai_analysis
                
        except asyncio.TimeoutError:
            # AI分析超时，保持默认值
            pass
        except Exception:
            # AI分析失败，保持默认值
            pass
        
        # 5. 添加性能监控数据
        response_time = int((time.time() - start_time) * 1000)
        cache_hit = not force_refresh and (datetime.now() - risk_score.timestamp) < timedelta(hours=24)
        
        response_data["_meta"] = {
            "response_time_ms": response_time,
            "cache_hit": cache_hit,
            "data_freshness": (datetime.now() - risk_score.timestamp).total_seconds() / 3600  # 小时
        }
        
        # 写入缓存（120秒）
        try:
            await cache.set(cache_key, response_data, expire=120)
        except Exception:
            pass

        return response_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching macro risk overview: {str(e)}")


@router.get("/macro/monetary-policy")
async def get_monetary_policy_analysis(
    session: AsyncSession = Depends(get_session)
):
    """获取货币政策分析
    
    返回详细的货币政策分析，包括：
    - 利率水平和趋势
    - 收益率曲线
    - 通胀压力
    - 货币供应量
    - 政策立场判断
    """
    try:
        macro_service = MacroIndicatorsService()
        
        # 获取货币政策立场
        monetary_policy = await macro_service.get_monetary_policy_stance()
        
        # 获取经济周期阶段
        economic_cycle = await macro_service.get_economic_cycle_phase()
        
        return {
            "monetary_policy": monetary_policy,
            "economic_cycle": economic_cycle,
            "last_updated": datetime.now()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching monetary policy analysis: {str(e)}")


@router.get("/macro/geopolitical-events")
async def get_geopolitical_events(
    days: int = Query(30, description="查询最近N天的事件"),
    category: Optional[str] = Query(None, description="事件类别筛选"),
    min_impact: int = Query(0, description="最小市场影响评分"),
    session: AsyncSession = Depends(get_session)
):
    """获取地缘政治事件
    
    返回最近的地缘政治事件列表，支持按类别和影响力筛选
    """
    try:
        geo_service = GeopoliticalEventsService()
        
        # 获取事件
        if category:
            from app.services.geopolitical_events_service import EventCategory
            events = await geo_service.get_events_by_category(
                EventCategory[category.upper()], 
                days
            )
        else:
            events = await geo_service.fetch_recent_events(days)
        
        # 按市场影响筛选
        if min_impact > 0:
            events = [e for e in events if e.market_impact_score >= min_impact]
        
        # 计算地缘政治风险评分
        risk_assessment = await geo_service.calculate_geopolitical_risk_score(days)
        
        return {
            "total_events": len(events),
            "risk_assessment": risk_assessment,
            "events": [
                {
                    "id": event.id,
                    "title": event.title,
                    "description": event.description,
                    "date": event.event_date.strftime("%Y-%m-%d"),
                    "category": event.category,
                    "severity": event.severity,
                    "affected_regions": event.affected_regions,
                    "affected_industries": event.affected_industries,
                    "market_impact_score": event.market_impact_score,
                    "news_source": event.news_source,
                    "news_url": event.news_url
                }
                for event in events
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching geopolitical events: {str(e)}")


@router.post("/macro/refresh")
async def refresh_macro_data(
    refresh_indicators: bool = Query(True, description="是否刷新宏观指标"),
    refresh_events: bool = Query(True, description="是否刷新地缘政治事件"),
    refresh_risk: bool = Query(True, description="是否刷新风险评分"),
    session: AsyncSession = Depends(get_session)
):
    """刷新宏观数据
    
    从外部数据源获取最新的宏观指标数据、地缘政治事件和风险评分。
    """
    try:
        results = {}
        
        # 刷新宏观指标
        if refresh_indicators:
            macro_service = MacroIndicatorsService()
            indicator_results = await macro_service.refresh_all_indicators()
            results["indicators"] = indicator_results
        
        # 刷新地缘政治事件
        if refresh_events:
            geo_service = GeopoliticalEventsService()
            events = await geo_service.fetch_recent_events(days=30, force_refresh=True)
            results["events"] = {
                "fetched": len(events),
                "message": f"Successfully fetched {len(events)} events"
            }
        
        # 刷新风险评分
        if refresh_risk:
            risk_service = MacroRiskScoringService()
            risk_score = await risk_service.calculate_macro_risk_score(use_cache=False)
            results["risk_score"] = {
                "overall_score": risk_score.overall_score,
                "risk_level": risk_score.risk_level,
                "timestamp": risk_score.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            }
        
        return {
            "message": "Macro data refresh completed",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing macro data: {str(e)}")
