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
from app.services.macro_indicators_service import MacroIndicatorsService
from app.services.macro_risk_scoring_service import MacroRiskScoringService
from app.services.geopolitical_events_service import GeopoliticalEventsService
from app.services.ai_analysis_service import AIAnalysisService
from app.broker.factory import make_option_broker_client
from app.providers.market_data_provider import MarketDataProvider

router = APIRouter()


# 依赖项：数据库会话（延迟导入避免循环依赖）
async def get_session():
    from app.main import SessionLocal
    async with SessionLocal() as session:
        yield session


@router.get("/positions/assessment", response_model=PositionsAssessmentResponse)
async def get_positions_assessment(
    window_days: int = Query(7, description="窗口期（天）"),
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
        # 获取当前持仓
        trade_client = make_option_broker_client()
        account_id = await trade_client.get_account_id()
        positions = await trade_client.list_underlying_positions(account_id)
        
        if not positions:
            return PositionsAssessmentResponse(
                positions=[],
                summary={
                    "total_positions": 0,
                    "avg_score": 0.0,
                    "high_risk_count": 0,
                    "buy_recommendation_count": 0
                }
            )
        
        # 提取股票代码
        symbols = [p.symbol for p in positions]
        
        # 批量计算评分
        scoring_service = PositionScoringService()
        scores = await scoring_service.get_all_position_scores(symbols, force_refresh=False)
        technical_service = TechnicalAnalysisService(session)
        
        # 构建响应
        position_assessments = []
        total_score = 0.0
        total_market_value = 0.0
        total_pnl = 0.0
        high_risk_count = 0
        buy_count = 0
        
        for position in positions:
            symbol = position.symbol
            score_data = scores.get(symbol)
            
            # 计算市值和盈亏
            market_value = position.quantity * position.last_price
            unrealized_pnl = (position.last_price - position.avg_price) * position.quantity
            unrealized_pnl_percent = ((position.last_price - position.avg_price) / position.avg_price * 100) if position.avg_price > 0 else 0
            
            snapshot = await technical_service.get_latest_trend_snapshot(
                symbol,
                account_id=account_id,
                timeframe="1D"
            )
            trend_snapshot = snapshot.to_dict() if snapshot else None

            # 构建持仓评估数据（即使没有评分也显示基本信息）
            assessment = {
                "symbol": symbol,
                "quantity": position.quantity,
                "avg_cost": position.avg_price,
                "current_price": position.last_price,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_percent": round(unrealized_pnl_percent, 2),
                # 评分数据（使用默认值如果不可用）
                "overall_score": score_data.overall_score if score_data else 50,
                "technical_score": score_data.technical_score if score_data else 50,
                "fundamental_score": score_data.fundamental_score if score_data else 50,
                "sentiment_score": score_data.sentiment_score if score_data else 50,
                "risk_level": score_data.risk_level if score_data else "MEDIUM",
                "recommendation": score_data.recommendation if score_data else "HOLD",
                "target_position": score_data.target_position if score_data else 0.5,
                "stop_loss": score_data.stop_loss if score_data else position.last_price * 0.9,
                "take_profit": score_data.take_profit if score_data else position.last_price * 1.1,
                "trend_snapshot": trend_snapshot
            }
            position_assessments.append(assessment)
            
            # 累加总计数据
            total_market_value += market_value
            total_pnl += unrealized_pnl
            
            # 统计数据
            score_value = score_data.overall_score if score_data else 50
            total_score += score_value
            
            risk = score_data.risk_level if score_data else "MEDIUM"
            if risk in ["HIGH", "EXTREME"]:
                high_risk_count += 1
                
            rec = score_data.recommendation if score_data else "HOLD"
            if rec in ["BUY", "STRONG_BUY"]:
                buy_count += 1
        
        avg_score = total_score / len(position_assessments) if position_assessments else 0.0
        
        return PositionsAssessmentResponse(
            positions=position_assessments,
            summary={
                "total_positions": len(position_assessments),
                "total_value": round(total_market_value, 2),
                "total_pnl": round(total_pnl, 2),
                "avg_score": round(avg_score, 2),
                "high_risk_count": high_risk_count,
                "buy_recommendation_count": buy_count
            }
        )
        
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
        
        # 刷新技术面数据（会写入日线趋势快照缓存表）
        technical_service = TechnicalAnalysisService(session)
        technical_results = {}
        for symbol in symbols:
            try:
                data = await technical_service.get_technical_analysis(
                    symbol,
                    timeframe="1D",
                    use_cache=False,
                    account_id=account_id
                )
                technical_results[symbol] = data is not None
            except Exception as e:
                print(f"Error refreshing technical for {symbol}: {e}")
                technical_results[symbol] = False
        
        # 刷新基本面数据
        fundamental_service = FundamentalAnalysisService()
        fundamental_results = await fundamental_service.batch_refresh_fundamentals(symbols)
        
        # 刷新综合评分
        scoring_service = PositionScoringService()
        score_results = {}
        market_provider = MarketDataProvider()
        for symbol in symbols:
            try:
                current_price = await market_provider.get_current_price(symbol)
                score = await scoring_service.calculate_position_score(
                    symbol, current_price, force_refresh=True
                )
                score_results[symbol] = score is not None
            except Exception as e:
                print(f"Error refreshing score for {symbol}: {e}")
                score_results[symbol] = False
        
        return {
            "message": "Refresh completed",
            "refreshed": symbols,
            "results": {
                "technical": technical_results,
                "fundamental": fundamental_results,
                "scores": score_results
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
                    "title": event.event_title,
                    "date": event.event_date.strftime("%Y-%m-%d"),
                    "category": event.category,
                    "severity": event.severity,
                    "impact_score": event.market_impact_score
                }
                for event in recent_events[:5] if hasattr(event, 'event_title')
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
                    "title": event.event_title,
                    "description": event.description,
                    "date": event.event_date.strftime("%Y-%m-%d"),
                    "category": event.category,
                    "severity": event.severity,
                    "affected_regions": event.affected_regions,
                    "affected_industries": event.affected_industries,
                    "market_impact_score": event.market_impact_score,
                    "source": event.source,
                    "source_url": event.source_url
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
