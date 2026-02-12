from typing import List
import json
import logging
import asyncio

from app.core.config import settings
from app.schemas.ai_advice import (
    AiAdviceRequest,
    AiAdviceResponse,
    AdviceOrderSuggestion,
    KlineAnalysisResponse,
    StockSymbol,
    SymbolSearchResponse,
)
from app.schemas.ai_state import AiStateView
from app.services.ai_analysis_service import _get_openai_client
from app.services.option_exposure_service import OptionExposureService
from app.services.risk_config_service import RiskConfigService
from app.services.symbol_risk_profile_service import SymbolRiskProfileService
from app.broker.factory import make_option_broker_client
from app.services.trading_plan_service import TradingPlanService
from app.providers.market_data_provider import MarketDataProvider
from app.providers.technical_calculator import TechnicalIndicatorCalculator

try:
    from tigeropen.common.consts import BarPeriod
except ImportError:
    BarPeriod = None

logger = logging.getLogger(__name__)


class AiAdviceService:
    """AI 决策助手服务。

    职责：
    - 聚合当前账户状态（RiskState + Exposure + 行为画像）
    - 构建一个结构化的 prompt，交给 GPT
    - 将模型返回的 JSON 解析为 AiAdviceResponse
    - 支持多周期 K 线深度分析
    """

    def __init__(self, session):
        self.session = session
        self.market_provider = MarketDataProvider()

    async def build_state_snapshot(self, account_id: str) -> AiStateView:
        """复用 /ai/state 的逻辑，内部构建出 AiStateView。"""
        from app.schemas.ai_state import AiStateView, LimitsView, SymbolBehaviorView, ExposureView

        risk = RiskConfigService(self.session)
        eff = await risk.get_effective_state(account_id)

        broker_client = make_option_broker_client()
        expo_svc = OptionExposureService(self.session, broker_client)
        expo = await expo_svc.get_account_exposure(account_id)
        eq = expo.equity_usd or 1.0
        
        exposure_view = ExposureView(
            equity_usd=expo.equity_usd,
            total_delta_notional_usd=expo.total_delta_notional_usd,
            total_gamma_usd=expo.total_gamma_usd,
            total_vega_usd=expo.total_vega_usd,
            total_theta_usd=expo.total_theta_usd,
            short_dte_gamma_usd=expo.short_dte_gamma_usd,
            short_dte_vega_usd=expo.short_dte_vega_usd,
            short_dte_theta_usd=expo.short_dte_theta_usd,
            delta_pct=expo.total_delta_notional_usd / eq,
            gamma_pct=expo.total_gamma_usd / eq,
            vega_pct=expo.total_vega_usd / eq,
            theta_pct=expo.total_theta_usd / eq,
            short_dte_gamma_pct=expo.short_dte_gamma_usd / eq,
            short_dte_theta_pct=expo.short_dte_theta_usd / eq,
        )

        symbols = list(eff.symbol_behavior_tiers.keys())
        prof_svc = SymbolRiskProfileService(self.session)
        behavior_stats = await prof_svc.get_behavior_stats(account_id, symbols)

        plan_service = TradingPlanService(self.session)
        plan_map = await plan_service.get_active_plans_by_symbols(account_id, symbols)
        plan_deviation_map = {}
        
        if plan_map:
            async def _price(sym: str):
                try:
                    return await self.market_provider.get_current_price(sym)
                except Exception:
                    return None

            price_tasks = {sym: asyncio.create_task(_price(sym)) for sym in plan_map.keys()}
            for sym, task in price_tasks.items():
                price = await task
                plan = plan_map.get(sym)
                if plan and price and float(plan.entry_price) > 0:
                    plan_deviation_map[sym] = min(abs(price - float(plan.entry_price)) / float(plan.entry_price) * 100, 100)

        limits_view = LimitsView(
            max_order_notional_usd=eff.limits.max_order_notional_usd,
            max_total_gamma_pct=eff.limits.max_total_gamma_pct,
            max_total_vega_pct=eff.limits.max_total_vega_pct,
            max_total_theta_pct=eff.limits.max_total_theta_pct,
        )

        symbol_views = {}
        for sym in symbols:
            stats = behavior_stats.get(sym)
            plan_deviation = plan_deviation_map.get(sym)
            if stats is None:
                bv = SymbolBehaviorView(
                    symbol=sym,
                    tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                    behavior_score=60,
                    sell_fly_score=50,
                    overtrade_score=50,
                    revenge_score=40,
                    discipline_score=60,
                    trade_count=0,
                    sell_fly_events=0,
                    sell_fly_extra_cost_ratio=0.0,
                    overtrade_index=0.0,
                    revenge_events=0,
                )
            else:
                discipline_score = stats.behavior_score
                if stats.overtrade_score > 70 and plan_deviation is not None and plan_deviation > 30:
                    discipline_score = max(0, discipline_score - 20)
                elif stats.overtrade_score > 70:
                    discipline_score = max(0, discipline_score - 10)

                bv = SymbolBehaviorView(
                    symbol=sym,
                    tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                    behavior_score=stats.behavior_score,
                    sell_fly_score=stats.sell_fly_score,
                    overtrade_score=stats.overtrade_score,
                    revenge_score=stats.revenge_trade_score,
                    discipline_score=discipline_score,
                    trade_count=stats.trade_count,
                    sell_fly_events=stats.sell_fly_events,
                    sell_fly_extra_cost_ratio=stats.sell_fly_extra_cost_ratio,
                    overtrade_index=stats.overtrade_index,
                    revenge_events=stats.revenge_events,
                )
            symbol_views[sym] = bv

        return AiStateView(
            trade_mode=eff.effective_trade_mode.value,
            limits=limits_view,
            exposure=exposure_view,
            symbols=symbol_views,
        )

    async def get_advice(self, req: AiAdviceRequest) -> AiAdviceResponse:
        """获取交易决策建议（原有逻辑）"""
        account_id = req.account_id or settings.TIGER_ACCOUNT
        snapshot = await self.build_state_snapshot(account_id)

        system_prompt = (
            "你是一名严谨的量化交易与风险管理助手，"
            "需要在既有风险限额和行为约束下，给出稳健的美股/港股交易建议。"
        )

        state_block = {
            "trade_mode": snapshot.trade_mode,
            "limits": snapshot.limits.model_dump() if hasattr(snapshot.limits, 'model_dump') else snapshot.limits.dict(),
            "exposure": snapshot.exposure.model_dump() if hasattr(snapshot.exposure, 'model_dump') else snapshot.exposure.dict(),
            "behavior": {k: (v.model_dump() if hasattr(v, 'model_dump') else v.dict()) for k, v in snapshot.symbols.items()},
        }

        user_block = {
            "goal": req.goal,
            "time_horizon": req.time_horizon,
            "risk_preference": req.risk_preference.model_dump() if hasattr(req.risk_preference, 'model_dump') else req.risk_preference.dict(),
            "notes": req.notes or "",
        }

        if not settings.OPENAI_API_KEY:
            return AiAdviceResponse(
                summary="占位建议：未配置 OPENAI_API_KEY，仅返回示例。",
                reasoning="真实环境下调会调用 LLM 综合风险与行为生成建议。",
                suggested_orders=[
                    AdviceOrderSuggestion(
                        symbol="AAPL", instrument="STOCK", side="BUY", quantity=0, note="示例订单", intent="ENTRY"
                    )
                ],
            )

        client = _get_openai_client()
        try:
            prompt = f"系统状态: {json.dumps(state_block)}\n用户请求: {json.dumps(user_block)}"
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            return AiAdviceResponse(**data)
        except Exception as e:
            logger.error(f"AiAdvice error: {e}")
            return AiAdviceResponse(summary="生成建议失败", reasoning=str(e), suggested_orders=[])

    async def search_symbols(self, query: str) -> SymbolSearchResponse:
        """模糊搜索美港股标的"""
        items = [
            StockSymbol(symbol="AAPL", name="苹果", market="US"),
            StockSymbol(symbol="TSLA", name="特斯拉", market="US"),
            StockSymbol(symbol="NVDA", name="英伟达", market="US"),
            StockSymbol(symbol="MSFT", name="微软", market="US"),
            StockSymbol(symbol="META", name="Meta", market="US"),
            StockSymbol(symbol="AMZN", name="亚马逊", market="US"),
            StockSymbol(symbol="GOOGL", name="谷歌", market="US"),
            StockSymbol(symbol="NFLX", name="奈飞", market="US"),
            StockSymbol(symbol="ROKU", name="Roku", market="US"),
            StockSymbol(symbol="AMD", name="AMD", market="US"),
            StockSymbol(symbol="BABA", name="阿里巴巴", market="US"),
            StockSymbol(symbol="00700", name="腾讯控股", market="HK"),
            StockSymbol(symbol="09988", name="阿里巴巴-SW", market="HK"),
            StockSymbol(symbol="03690", name="美团-W", market="HK"),
            StockSymbol(symbol="09888", name="百度集团-SW", market="HK"),
            StockSymbol(symbol="01024", name="快手-W", market="HK"),
            StockSymbol(symbol="01810", name="小米集团-W", market="HK"),
        ]
        
        try:
            broker_client = make_option_broker_client()
            account_id = await broker_client.get_account_id()
            if account_id:
                positions = await broker_client.list_underlying_positions(account_id)
                for p in positions:
                    if not any(it.symbol == p.symbol for it in items):
                        market = "HK" if p.symbol.isdigit() and len(p.symbol) >= 4 else "US"
                        items.append(StockSymbol(symbol=p.symbol, name=p.symbol, market=market))
        except: pass
            
        if not query: return SymbolSearchResponse(items=items[:20])
            
        q = query.upper()
        filtered = [it for it in items if q in it.symbol.upper() or (it.name and q in it.name)]
        
        # 如果没有任何匹配，且输入看起来像一个代码，尝试动态增加
        if not filtered and len(q) >= 2 and len(q) <= 6:
            market = "HK" if q.isdigit() else "US"
            filtered.append(StockSymbol(symbol=q, name=q, market=market))
            
        return SymbolSearchResponse(items=filtered)

    async def analyze_stock_kline(self, symbol: str) -> KlineAnalysisResponse:
        """多周期K线走势深度分析"""
        if BarPeriod is None:
            return KlineAnalysisResponse(
                symbol=symbol, prediction="无法获取数据", suggestion="Tiger SDK 未安装",
                direction="NEUTRAL", action="HOLD", details="当前环境缺少 tigeropen SDK，无法提取多周期K线。"
            )

        periods = [
            (BarPeriod.WEEK, "1y", "周线(Weekly)"),
            (BarPeriod.DAY, "6mo", "日线(Daily)"),
            (BarPeriod.FOUR_HOURS, "1mo", "4小时(4h)"),
            (BarPeriod.TWO_HOURS, "2w", "2小时(2h)"),
            (BarPeriod.ONE_HOUR, "1w", "1小时(1h)")
        ]
        
        kline_data = {}
        for bar_p, p_str, label in periods:
            try:
                df = await self.market_provider._get_tiger_bars(symbol, p_str, bar_period=bar_p)
                if df is not None and not df.empty:
                    subset = df.tail(15)[["Open", "High", "Low", "Close", "Volume"]].copy()
                    subset.index = subset.index.strftime('%Y-%m-%d %H:%M')
                    kline_data[label] = subset.to_dict(orient='index')
                else: kline_data[label] = "暂无数据"
            except Exception as e: kline_data[label] = f"获取失败: {str(e)}"

        client = _get_openai_client()
        if not client:
            logger.info(f"OpenAI not configured, using rule-based analysis for {symbol}")
            return await self._get_rule_based_kline_analysis(symbol)

        prompt = f"""
你是一名顶级华尔街对冲基金交易员，擅长结合多周期（Weekly, Daily, 4h, 2h, 1h）K 线进行趋势判断。
分析标的: {symbol}
K线快照: {json.dumps(kline_data, indent=2, ensure_ascii=False)}

输出 JSON:
{{
  "prediction": "走势预测摘要",
  "suggestion": "操作建议摘要",
  "direction": "LONG/SHORT/NEUTRAL",
  "action": "BUY/SELL/HOLD/EMPTY/INCREASE",
  "details": "深度分析细节"
}}
"""
        try:
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "system", "content": "你是一名资深华尔街分析师。"}, {"role": "user", "content": prompt}],
                temperature=0.3, response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            return KlineAnalysisResponse(symbol=symbol, **data)
        except Exception as e:
            logger.error(f"AI kline analysis error: {e}")
            # 如果是配额问题或连接问题，触发降级方案
            if "insufficient_quota" in str(e).lower() or "429" in str(e):
                logger.info(f"Triggering rule-based fallback analysis for {symbol} due to OpenAI quota limit")
                return await self._get_rule_based_kline_analysis(symbol)
                
            return KlineAnalysisResponse(
                symbol=symbol, prediction="分析失败", suggestion="请重试",
                direction="NEUTRAL", action="HOLD", details=str(e)
            )

    async def _get_rule_based_kline_analysis(self, symbol: str) -> KlineAnalysisResponse:
        """模型降级：基于规则系统生成技术面分析报告"""
        try:
            # 获取日线数据
            df = await self.market_provider.get_historical_data(symbol, period="1y", interval="1d")
            if df is None or df.empty:
                return KlineAnalysisResponse(
                    symbol=symbol, prediction="无法获取行行情数据", suggestion="请检查标的代码",
                    direction="NEUTRAL", action="HOLD", details="降级引擎无法拉取到足够的价格数据进行分析。"
                )

            calc = TechnicalIndicatorCalculator()
            df = calc.calculate_all_indicators(df)
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            # 1. 趋势判断
            trend_dir, trend_strength = calc.identify_trend(df)
            
            # 2. RSI 状态
            rsi_val = latest.get('RSI_14', 50)
            rsi_status, rsi_signal = calc.identify_rsi_status(rsi_val)
            
            # 3. MACD
            macd_signal = calc.identify_macd_signal(df)
            
            # 4. 支撑阻力
            support, resistance = calc.identify_support_resistance(df)
            
            # 构建预测
            trend_desc = {
                "BULLISH": "处于上升趋势中",
                "BEARISH": "处于下降趋势中",
                "SIDEWAYS": "处于区间震荡状态"
            }.get(trend_dir, "趋势不明确")
            
            prediction = f"【系统降级报告】当前标的{trend_desc}，趋势强度 {trend_strength}%。"
            if rsi_status != "NEUTRAL":
                prediction += f" RSI 处于{rsi_status.lower()}区域({round(rsi_val, 1)})。"
            
            # 构建建议
            suggestion = "维持观望"
            action = "HOLD"
            direction = "NEUTRAL"
            
            if trend_dir == "BULLISH":
                direction = "LONG"
                if rsi_signal == "BUY" or macd_signal == "BULLISH_CROSSOVER":
                    suggestion = "建议考虑买入或加仓"
                    action = "BUY"
                else:
                    suggestion = "建议持股待涨"
                    action = "HOLD"
            elif trend_dir == "BEARISH":
                direction = "SHORT"
                if rsi_signal == "SELL" or macd_signal == "BEARISH_CROSSOVER":
                    suggestion = "风险较高，建议择机退出"
                    action = "SELL"
                else:
                    suggestion = "弱势整理，减仓观望"
                    action = "EMPTY"
            
            # 详细逻辑
            details = f"【全量规则引擎分析 - 降级报告】\n\n"
            details += f"1. 趋势分析: {trend_desc} (强度 {trend_strength})\n"
            details += f"- 价格相对于 MA50: {'站上' if latest['Close'] > latest.get('MA_50', 0) else '跌破'}\n"
            details += f"- 均线系统现状: {'多头排列' if latest.get('MA_20', 0) > latest.get('MA_50', 0) else '空头/平衡'}\n\n"
            
            details += f"2. 指标详情:\n"
            details += f"- RSI (14天): {round(rsi_val, 2)} ({rsi_status})\n"
            details += f"- MACD信号: {macd_signal.replace('_', ' ')}\n"
            details += f"- 波动率 (ATR): {round(latest.get('ATR_14', 0), 2)}\n\n"
            
            details += f"3. 关键位识别:\n"
            if resistance:
                details += f"- 阻力参考: {' / '.join([str(round(r, 2)) for r in resistance[:2]])}\n"
            if support:
                details += f"- 支撑参考: {' / '.join([str(round(s, 2)) for s in support[:2]])}\n\n"
            
            details += "注意: 由于 AI 接口配额受限或未配置，系统已自动切换至本地专家规则引擎。该分析基于技术面量化规则，不包含 AI 语义理解或宏观新闻分析。"

            return KlineAnalysisResponse(
                symbol=symbol,
                prediction=prediction,
                suggestion=suggestion,
                direction=direction,
                action=action,
                details=details
            )
        except Exception as ex:
            logger.error(f"Rule-based analysis failed: {ex}")
            return KlineAnalysisResponse(
                symbol=symbol, prediction="降级分析亦失败", suggestion="请稍后重试",
                direction="NEUTRAL", action="HOLD", details=f"AI 额度超限且本地规则引擎出错: {str(ex)}"
            )
