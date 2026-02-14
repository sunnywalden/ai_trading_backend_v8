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
from app.services.ai_analysis_service import AIAnalysisService
from app.services.ai_client_manager import call_ai_with_fallback
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

        try:
            prompt = f"系统状态: {json.dumps(state_block)}\n用户请求: {json.dumps(user_block)}"
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            # 使用多提供商降级调用（OpenAI → DeepSeek）
            content, provider = await call_ai_with_fallback(
                messages=messages,
                response_format={"type": "json_object"},
            )
            
            if not content:
                return AiAdviceResponse(summary="生成建议失败", reasoning="所有AI提供商均不可用", suggested_orders=[])
            
            data = json.loads(content)
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
        """多周期K线走势深度分析（华尔街专业视角）"""
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
                    subset = df.tail(20)[["Open", "High", "Low", "Close", "Volume"]].copy()
                    subset.index = subset.index.strftime('%Y-%m-%d %H:%M')
                    kline_data[label] = subset.to_dict(orient='index')
                else: kline_data[label] = "暂无数据"
            except Exception as e: kline_data[label] = f"获取失败: {str(e)}"

        # 华尔街专业级分析框架
        prompt = f"""
你是华尔街顶级对冲基金的首席投资官（CIO），拥有20年+ sell-side 和 buy-side 经验，专精于多资产类别量化分析和宏观策略。

=== 分析任务 ===
标的代码: {symbol}
多周期K线数据: {json.dumps(kline_data, indent=2, ensure_ascii=False)}

=== 分析框架（Investment Thesis Framework）===
请基于以下维度进行综合评估：

1. **技术面多周期共振分析 (Technical Multi-Timeframe Confluence)**
   - 主趋势确认（周线 -> 日线 -> 小时线的嵌套结构）
   - 关键支撑/阻力位（Fibonacci、前高低、心理价位）
   - 动量与背离（价格动量 vs 成交量动量）
   - 波动率状态（ATR、Bollinger Bands收缩/扩张）
   
2. **市场结构与资金流分析 (Market Structure & Flow)**
   - 成交量特征（放量突破、缩量整理、异常堆积）
   - 买卖压力平衡（大单方向、逐笔成交分布）
   - 关键形态（Head & Shoulders、Cup & Handle、Wedge等）
   
3. **风险收益比与仓位管理 (Risk/Reward & Position Sizing)**
   - 入场点（Entry）：最优价位及触发条件
   - 止损点（Stop Loss）：技术止损位及最大允许亏损
   - 止盈点（Take Profit）：分批获利目标价
   - 风险收益比（R:R Ratio）：至少 1:2 才值得交易
   - 建议仓位：基于波动率和确定性的Kelly公式参考
   
4. **催化剂识别 (Catalysts & Triggers)**
   - 短期催化剂（1-2周）：技术突破、财报、新闻事件
   - 中长期驱动（1-6月）：行业趋势、政策变化、周期轮动
   
5. **情景分析 (Scenario Analysis)**
   - 牛市情景（概率X%）：突破后的上涨空间
   - 熊市情景（概率Y%）：跌破后的下跌空间
   - 中性情景（概率Z%）：震荡区间及持续时间
   
6. **操作建议分级 (Conviction Level)**
   - 高确定性（High Conviction）：20-30% 仓位
   - 中等确定性（Medium）：10-15% 仓位
   - 低确定性/观望（Low/Wait）：0-5% 仓位

=== 输出 JSON 格式 ===
{{
  "prediction": "<50字核心论点，类似sell-side研报Executive Summary>",
  "suggestion": "<操作建议：明确买入/卖出/持有，附带仓位大小建议>",
  "direction": "LONG/SHORT/NEUTRAL",
  "action": "BUY/SELL/HOLD/EMPTY/INCREASE",
  "details": "<结构化分析报告，包含：\n1. 技术面多周期共振\n2. 市场结构与资金流\n3. 风险收益比计算（Entry/SL/TP）\n4. 催化剂与时间窗口\n5. 情景分析（牛/熊/中性）\n6. 持有期建议\n7. 风险提示>"
}}

注意：
- 使用华尔街行业术语（如 "higher high", "consolidation", "breakout", "retracement" 等）
- 量化你的判断（如 "60% 概率突破", "风险收益比 1:3"）
- 提供可执行的价格锚点（如 "突破 $150 后加仓至 15%"）
- 避免模糊表述，给出明确的数字和逻辑链条
"""
        messages = [
            {"role": "system", "content": "你是华尔街顶级对冲基金CIO，擅长多维度量化分析和风险管理。你的分析报告以精准、可执行著称。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            # 使用多提供商降级调用（OpenAI → DeepSeek）
            content, provider = await call_ai_with_fallback(
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            
            if not content:
                logger.info(f"AI Advisor: Analysis fallback to rule-based engine for {symbol}")
                return await self._get_rule_based_kline_analysis(symbol)
            
            data = json.loads(content)
            
            # 数据清洗：确保 direction 和 action 符合 Literal 要求
            if "direction" in data:
                d = str(data["direction"]).upper()
                if d not in ["LONG", "SHORT", "NEUTRAL"]:
                    if "LONG" in d: data["direction"] = "LONG"
                    elif "SHORT" in d: data["direction"] = "SHORT"
                    else: data["direction"] = "NEUTRAL"
                else:
                    data["direction"] = d
            
            if "action" in data:
                a = str(data["action"]).upper()
                valid_actions = ["BUY", "SELL", "HOLD", "EMPTY", "INCREASE"]
                if a not in valid_actions:
                    # 尝试匹配关键词
                    if "BUY" in a: data["action"] = "BUY"
                    elif "SELL" in a: data["action"] = "SELL"
                    elif "INCREASE" in a: data["action"] = "INCREASE"
                    elif "REDUCE" in a: data["action"] = "SELL"  # 映射
                    else: data["action"] = "HOLD"
                else:
                    data["action"] = a
            
            # 强化：处理 details 可能被 AI 返回为对象的情况
            if "details" in data and not isinstance(data["details"], str):
                if isinstance(data["details"], (dict, list)):
                    data["details"] = json.dumps(data["details"], ensure_ascii=False, indent=2)
                else:
                    data["details"] = str(data["details"])

            return KlineAnalysisResponse(symbol=symbol, **data)
        except Exception as e:
            logger.error(f"AI Advisor: Analysis error for {symbol} | {e}")
            logger.info(f"AI Advisor: Triggering rule-based fallback for {symbol}")
            return await self._get_rule_based_kline_analysis(symbol)

    async def _get_rule_based_kline_analysis(self, symbol: str) -> KlineAnalysisResponse:
        """模型降级：基于规则系统生成技术面分析报告"""
        try:
            # 获取日线数据
            df = await self.market_provider.get_historical_data(symbol, period="1y", interval="1d")
            if df is None or df.empty:
                return KlineAnalysisResponse(
                    symbol=symbol, prediction="无法获取行情数据", suggestion="请检查标的代码",
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
            
            # 5. 成交量分析（专业增强）
            vol_avg_20 = df['Volume'].tail(20).mean()
            vol_ratio = latest.get('Volume', 0) / vol_avg_20 if vol_avg_20 > 0 else 1.0
            vol_signal = "放量" if vol_ratio > 1.5 else ("缩量" if vol_ratio < 0.6 else "平量")
            
            # 6. 波动率和风险评估
            atr = latest.get('ATR_14', 0)
            price = latest.get('Close', 0)
            volatility_pct = (atr / price * 100) if price > 0 else 0
            
            # 7. 动量评分（0-100）
            momentum_score = 50  # 中性基准
            if trend_dir == "BULLISH":
                momentum_score += trend_strength * 0.3
            elif trend_dir == "BEARISH":
                momentum_score -= trend_strength * 0.3
            if rsi_val > 60:
                momentum_score += 10
            elif rsi_val < 40:
                momentum_score -= 10
            if macd_signal == "BULLISH_CROSSOVER":
                momentum_score += 15
            elif macd_signal == "BEARISH_CROSSOVER":
                momentum_score -= 15
            momentum_score = max(0, min(100, momentum_score))
            
            # 构建华尔街风格的预测
            trend_desc = {
                "BULLISH": "上行趋势（Uptrend）",
                "BEARISH": "下行趋势（Downtrend）",
                "SIDEWAYS": "横盘整理（Consolidation）"
            }.get(trend_dir, "趋势不明（Unclear Trend）")
            
            prediction = f"【量化规则引擎】{trend_desc}，强度{trend_strength}%。动量评分{round(momentum_score)}/100。"
            if rsi_status != "NEUTRAL":
                prediction += f" RSI {round(rsi_val, 1)} 处于{rsi_status}区。"
            prediction += f" {vol_signal}（Vol比率{round(vol_ratio, 2)}x）。"
            
            # 风险收益比计算（基于支撑阻力）
            entry = price
            stop_loss = support[0] if support and len(support) > 0 else price * 0.95
            take_profit = resistance[0] if resistance and len(resistance) > 0 else price * 1.05
            risk = abs(entry - stop_loss)
            reward = abs(take_profit - entry)
            rr_ratio = reward / risk if risk > 0 else 0
            
            # 构建建议（更专业的表述）
            suggestion = "观望等待（Wait & Watch）"
            action = "HOLD"
            direction = "NEUTRAL"
            position_size = "0%"
            
            if trend_dir == "BULLISH" and momentum_score > 60:
                direction = "LONG"
                if rsi_signal == "BUY" or macd_signal == "BULLISH_CROSSOVER":
                    if rr_ratio >= 2.0:
                        suggestion = f"高确定性买入机会（Entry: ${round(entry, 2)}, SL: ${round(stop_loss, 2)}, TP: ${round(take_profit, 2)}）"
                        action = "BUY"
                        position_size = "15-20%"
                    else:
                        suggestion = f"中等确定性买入（R:R={round(rr_ratio, 2)}不理想，轻仓试探）"
                        action = "BUY"
                        position_size = "5-10%"
                else:
                    suggestion = "趋势向上但需等待回调（Wait for Pullback）"
                    action = "HOLD"
                    position_size = "0-5%"
            elif trend_dir == "BEARISH" and momentum_score < 40:
                direction = "SHORT"
                if rsi_signal == "SELL" or macd_signal == "BEARISH_CROSSOVER":
                    suggestion = f"风险较高，建议减仓或止损（Exit: ${round(entry, 2)}, Rebound Target: ${round(resistance[0] if resistance else entry*1.03, 2)}）"
                    action = "SELL"
                    position_size = "减至 0-5%"
                else:
                    suggestion = "弱势整理，降低仓位观望（Reduce & Watch）"
                    action = "EMPTY"
                    position_size = "0-5%"
            elif abs(50 - momentum_score) < 15:
                suggestion = "区间震荡，等待方向明确（Range-bound, Wait for Breakout）"
                action = "HOLD"
                position_size = "维持现有仓位"
            
            # 详细逻辑（华尔街投研报告风格）
            details = f"=== 量化规则引擎分析报告（AI降级模式）===\n\n"
            details += f"** I. 技术面多周期分析 **\n"
            details += f"1. 主趋势：{trend_desc}（强度 {trend_strength}/100）\n"
            details += f"   - 价格 vs MA50: {'突破' if latest['Close'] > latest.get('MA_50', 0) else '跌破'} (${round(latest.get('MA_50', 0), 2)})\n"
            details += f"   - 均线排列: {'多头' if latest.get('MA_20', 0) > latest.get('MA_50', 0) else '空头/平衡'}\n"
            details += f"   - 动量评分: {round(momentum_score)}/100\n\n"
            
            details += f"2. 技术指标读数:\n"
            details += f"   - RSI(14): {round(rsi_val, 2)} → {rsi_status} ({rsi_signal})\n"
            details += f"   - MACD信号: {macd_signal.replace('_', ' ')}\n"
            details += f"   - 波动率(ATR): {round(atr, 2)} ({round(volatility_pct, 2)}% of price)\n\n"
            
            details += f"** II. 市场结构与资金流 **\n"
            details += f"3. 成交量分析:\n"
            details += f"   - 当前量: {int(latest.get('Volume', 0)):,}\n"
            details += f"   - 20日均量: {int(vol_avg_20):,}\n"
            details += f"   - 状态: {vol_signal}（比率 {round(vol_ratio, 2)}x）\n\n"
            
            details += f"4. 关键价位识别:\n"
            if resistance:
                details += f"   - 阻力位（Resistance）: {', '.join([f'${round(r, 2)}' for r in resistance[:3]])}\n"
            if support:
                details += f"   - 支撑位（Support）: {', '.join([f'${round(s, 2)}' for s in support[:3]])}\n"
            details += f"\n"
            
            details += f"** III. 风险收益比与仓位管理 **\n"
            details += f"5. 交易计划（Trade Setup）:\n"
            details += f"   - 入场点（Entry）: ${round(entry, 2)}\n"
            details += f"   - 止损位（Stop Loss）: ${round(stop_loss, 2)} (-{round((entry-stop_loss)/entry*100, 1)}%)\n"
            details += f"   - 止盈位（Take Profit）: ${round(take_profit, 2)} (+{round((take_profit-entry)/entry*100, 1)}%)\n"
            details += f"   - R:R 比率: 1:{round(rr_ratio, 2)} {'✓ 符合标准' if rr_ratio >= 2.0 else '⚠️ 偏低'}\n"
            details += f"   - 建议仓位: {position_size}\n\n"
            
            details += f"** IV. 持有期与风险提示 **\n"
            details += f"6. 时间窗口：\n"
            if trend_dir == "BULLISH":
                details += f"   - 预期持有期: 1-4周（取决于目标价触达速度）\n"
            elif trend_dir == "BEARISH":
                details += f"   - 建议退出期: 尽快（或反弹至阻力位后离场）\n"
            else:
                details += f"   - 观望期: 待区间突破（上破买入，下破离场）\n"
            details += f"\n"
            details += f"7. 风险警示：\n"
            if volatility_pct > 3:
                details += f"   ⚠️ 高波动环境（{round(volatility_pct, 1)}%），控制仓位\n"
            if rsi_val > 80:
                details += f"   ⚠️ RSI严重超买，警惕回调风险\n"
            elif rsi_val < 20:
                details += f"   ⚠️ RSI严重超卖，可能存在超跌反弹\n"
            if vol_ratio < 0.5:
                details += f"   ⚠️ 成交量萎缩，缺乏资金参与\n"
            details += f"\n"
            details += f"---\n"
            details += f"注意：AI接口不可用，已切换至量化规则引擎。该分析基于纯技术指标，不包含基本面、新闻情绪、宏观环境等因素。"

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
