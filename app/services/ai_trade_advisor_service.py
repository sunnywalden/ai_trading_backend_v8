"""
AI 交易决策服务 - 统一的智能交易入口

核心流程：
1. 用户输入感兴趣的标的列表
2. 系统并行调用多维研究模块进行评估
3. AI 综合研判，生成交易决策（方向/仓位/入场价/止损止盈）
4. 用户确认后一键智能执行

整合了原「交易助手」和「执行中心」的功能，提供 AI 驱动的决策支持。
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.providers.market_data_provider import MarketDataProvider
from app.broker.factory import make_option_broker_client
from app.engine.order_executor import OrderExecutor
from app.services.ai_analysis_service import AIAnalysisService
from app.services.ai_client_manager import call_ai_with_fallback
from app.services.trading_plan_service import TradingPlanService
from app.models.trading_signal import TradingSignal, SignalType, SignalStatus, SignalSource
from app.models.ai_evaluation_history import AIEvaluationHistory

logger = logging.getLogger(__name__)


class AITradeAdvisorService:
    """AI 交易决策服务

    职责:
    - 多维度评估标的（技术面 + 基本面 + 宏观 + K线）
    - AI 综合研判生成交易决策
    - 智能执行（自动控制仓位、价格、方向）
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.market_data = MarketDataProvider()
        self.broker = make_option_broker_client()
        self.ai_service = AIAnalysisService()

    # ------------------------------------------------------------------
    # 1. 多维度评估
    # ------------------------------------------------------------------

    async def evaluate_symbols(
        self,
        symbols: List[str],
        account_id: Optional[str] = None,
        save_history: bool = True,
        locale: str = "zh"
    ) -> List[Dict[str, Any]]:
        """
        并行评估多个标的，返回每个标的的多维分析 + AI 交易决策。

        每个标的返回:
        - 实时价格
        - 技术面评分 + 摘要
        - 基本面评分 + 摘要
        - K线走势分析（方向 + action）
        - AI 综合决策（方向 / 置信度 / 入场价 / 止损 / 止盈 / 仓位）
        """
        account_id = account_id or settings.TIGER_ACCOUNT
        
        tasks = [self._evaluate_single(sym, account_id, locale=locale) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        evaluations = []
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.error(f"评估 {sym} 失败: {result}")
                evaluations.append({
                    "symbol": sym,
                    "status": "error",
                    "error": str(result),
                })
            else:
                evaluations.append(result)
        
        # 保存评估历史（覆盖已有记录）
        if save_history:
            await self._save_evaluation_history(evaluations, account_id)
        
        return evaluations

    async def _evaluate_single(self, symbol: str, account_id: str, locale: str = "zh") -> Dict[str, Any]:
        """单标的多维评估"""
        # 并行获取各维度数据
        price_task = self._safe_get_price(symbol)
        technical_task = self._safe_get_technical(symbol)
        fundamental_task = self._safe_get_fundamental(symbol)
        kline_task = self._safe_get_kline_analysis(symbol)
        equity_task = self._safe_get_equity(account_id)

        price, technical, fundamental, kline, equity = await asyncio.gather(
            price_task, technical_task, fundamental_task, kline_task, equity_task
        )

        # 构建评估摘要，交给 AI 做综合决策
        decision = await self._generate_ai_decision(
            symbol=symbol,
            price=price,
            technical=technical,
            fundamental=fundamental,
            kline=kline,
            equity=equity,
        )

        return {
            "symbol": symbol,
            "status": "ok",
            "current_price": price,
            "dimensions": {
                "technical": technical,
                "fundamental": fundamental,
                "kline": kline,
            },
            "decision": decision,
        }

    # ------------------------------------------------------------------
    # 2. AI 综合决策
    # ------------------------------------------------------------------

    async def _generate_ai_decision(
        self,
        symbol: str,
        price: Optional[float],
        technical: Dict[str, Any],
        fundamental: Dict[str, Any],
        kline: Dict[str, Any],
        equity: float,
    ) -> Dict[str, Any]:
        """
        调用 GPT 综合多维数据，给出交易决策。
        返回: direction, confidence, action, entry_price, stop_loss,
              take_profit, position_pct, reasoning
        """
        context = {
            "symbol": symbol,
            "current_price": price,
            "account_equity": equity,
            "technical": {
                "score": technical.get("score"),
                "trend": technical.get("trend"),
                "rsi": technical.get("rsi"),
                "macd_signal": technical.get("macd_signal"),
                "summary": technical.get("summary", ""),
            },
            "fundamental": {
                "score": fundamental.get("score"),
                "pe_ratio": fundamental.get("pe_ratio"),
                "roe": fundamental.get("roe"),
                "revenue_growth": fundamental.get("revenue_growth"),
                "summary": fundamental.get("summary", ""),
            },
            "kline_analysis": {
                "direction": kline.get("direction"),
                "action": kline.get("action"),
                "prediction": kline.get("prediction"),
                "suggestion": kline.get("suggestion"),
            },
        }

        # 华尔街专业级系统提示词
        system_prompt = """你是华尔街顶级对冲基金的交易委员会（Investment Committee）成员，拥有 20 年+ sell-side 和 buy-side 经验，专精于风险管理、仓位分配和多维度综合评估。你的决策以精准、可执行、风险可控著称。

=== 决策框架（Decision Framework）===
基于多维度输入数据（技术面、基本面、K线分析），进行华尔街级别的综合评估：

1. **多维数据融合 (Multi-Dimensional Synthesis)**
   - 技术面、基本面、K线分析的一致性检验
   - 冲突信号的权重调整（如技术偏多但基本面偏空）
   - 市场周期位置判断（早期、中期、晚期）

2. **风险收益比验证 (Risk/Reward Validation)**
   - 入场点（Entry）：基于技术位和价值锚点
   - 止损点（Stop Loss）：技术止损 + 最大可承受亏损
   - 止盈点（Take Profit）：分批获利策略
   - **R:R Ratio：必须 ≥ 1:2 才值得交易**
   - 盈亏比不足时，务必建议 HOLD 或 AVOID

3. **仓位管理决策 (Position Sizing Logic)**
   - 基于 Kelly 公式：f* = (p × b - q) / b（p=胜率, q=败率, b=赔率）
   - 修正系数：考虑波动率、相关性、账户集中度
   - 建议仓位范围：
     * 高确定性（80%+ confidence）：15-30%
     * 中等确定性（60-79%）：8-15%
     * 低确定性（<60%）：0-8% 或观望

4. **催化剂时间窗口 (Catalyst Timeline)**
   - 短期催化剂（1-2周）：技术突破、财报发布、关键事件
   - 中长期驱动（1-6月）：行业趋势、政策变化、估值修复
   - 明确交易持有期建议

5. **情景分析与概率分布 (Scenario Probability)**
   - 牛市情景（概率X%）：突破后的上涨空间和目标价
   - 熊市情景（概率Y%）：跌破后的下跌风险和止损位
   - 中性情景（概率Z%）：震荡盘整的区间和时间
   - 期望收益 = Σ(概率 × 收益)

6. **风险监控与退出策略 (Risk Monitoring & Exit)**
   - 风险级别：LOW（低波动+高确定性）/ MEDIUM / HIGH（高波动+低确定性）
   - 动态调整触发条件：价格突破、基本面变化、市场环境恶化
   - 强制平仓条件：亏损超过预期、催化剂失效

=== 严格输出 JSON 格式 ===
{
  "direction": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": 0-100 的整数（基于信号一致性和R:R比）,
  "action": "BUY" | "SELL" | "HOLD" | "AVOID",
  "entry_price": 最优入场价（float，HOLD/AVOID 时为 null）,
  "stop_loss": 技术止损价（float 或 null）,
  "take_profit": 目标获利价（float 或 null）,
  "position_pct": 建议仓位比例（0.01-0.30，基于Kelly公式修正）,
  "reasoning": "150字以内核心逻辑：1)多维信号综合判断 2)R:R比计算 3)仓位逻辑 4)催化剂 5)风险提示",
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "key_factors": ["关键因素1", "关键因素2", "关键因素3"],
  "risk_reward_ratio": "R:R比例，格式如 '1:2.5'",
  "scenarios": {
    "bull": {"probability": 0-100整数, "target": 价格float, "upside": "涨幅%"},
    "bear": {"probability": 0-100整数, "support": 价格float, "downside": "跌幅%"},
    "neutral": {"probability": 0-100整数, "range": "区间描述"}
  },
  "catalysts": {
    "short_term": "1-2周内的催化剂",
    "mid_term": "1-6月的驱动因素"
  },
  "holding_period": "建议持有周期，如 '2-4周' 或 '1-3个月'"
}

=== 决策原则（Critical Rules）===
- **风险收益比不足 1:2 时，必须建议 HOLD 或 AVOID**
- 技术面评分 < 40 且趋势 BEARISH → 倾向 AVOID 或 SHORT
- 基本面评分 > 70 + 技术面上升趋势 → 积极 BUY，仓位可适当提高
- K线 direction 与技术面趋势矛盾 → 降低置信度和仓位
- **置信度 < 60% 时，action 应为 HOLD 而非 BUY/SELL**
- 止损幅度控制在 3%-8%，止盈至少为止损的 2 倍（R:R ≥ 1:2）
- 单标的仓位不超过总资产的 30%
- 使用华尔街术语（如 "consolidation", "breakout", "mean reversion"）
- 量化所有判断（避免 "可能"、"或许" 等模糊词）
- 给出可执行的价格锚点和仓位数字"""

        lang_instruction = "IMPORTANT: You MUST respond in English for text fields like 'reasoning', 'key_factors', 'scenarios' and 'catalysts'." if locale == "en" else "重要提示：必须使用中文返回 'reasoning', 'key_factors', 'scenarios' 和 'catalysts' 等文本字段。"
        system_prompt += f"\n\n{lang_instruction}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        
        try:
            # 使用多提供商降级调用（OpenAI → DeepSeek）
            content, provider = await call_ai_with_fallback(
                messages=messages,
                temperature=0.3,  # 提高一点但保持决策稳定性
                response_format={"type": "json_object"},
            )
            
            if content:
                data = json.loads(content)
                return self._validate_decision(data, price)
            else:
                logger.warning(f"AI 决策生成失败 ({symbol}): 所有提供商均不可用，降级到规则引擎")
        except Exception as e:
            logger.warning(f"AI 决策生成异常 ({symbol}): {e}，降级到规则引擎")

        # 规则引擎降级
        return self._rule_based_decision(symbol, price, technical, fundamental, kline, equity)

    def _validate_decision(self, data: Dict, price: Optional[float]) -> Dict[str, Any]:
        """校验 AI 返回的决策数据"""
        direction = data.get("direction", "NEUTRAL")
        confidence = max(0, min(100, int(data.get("confidence", 50))))
        action = data.get("action", "HOLD")
        position_pct = max(0.01, min(0.30, float(data.get("position_pct", 0.10))))

        # 低置信度强制 HOLD
        if confidence < 50 and action in ("BUY", "SELL"):
            action = "HOLD"

        entry_price = data.get("entry_price")
        stop_loss = data.get("stop_loss")
        take_profit = data.get("take_profit")

        # 校验价格合理性
        if price and entry_price:
            entry_price = float(entry_price)
            if abs(entry_price - price) / price > 0.15:
                entry_price = price  # 偏差过大，用当前价

        if stop_loss:
            stop_loss = float(stop_loss)
        if take_profit:
            take_profit = float(take_profit)

        return {
            "direction": direction,
            "confidence": confidence,
            "action": action,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_pct": position_pct,
            "reasoning": data.get("reasoning", ""),
            "risk_level": data.get("risk_level", "MEDIUM"),
            "key_factors": data.get("key_factors", []),
        }

    def _rule_based_decision(
        self,
        symbol: str,
        price: Optional[float],
        technical: Dict,
        fundamental: Dict,
        kline: Dict,
        equity: float,
    ) -> Dict[str, Any]:
        """规则引擎降级决策"""
        tech_score = technical.get("score", 50) or 50
        fund_score = fundamental.get("score", 50) or 50
        kline_dir = kline.get("direction", "NEUTRAL")
        kline_action = kline.get("action", "HOLD")

        # 综合评分
        composite = tech_score * 0.4 + fund_score * 0.3 + (70 if kline_dir == "LONG" else 30 if kline_dir == "SHORT" else 50) * 0.3
        confidence = int(min(100, max(0, composite)))

        # 方向判断
        bullish_signals = sum([
            tech_score > 60,
            fund_score > 60,
            kline_dir == "LONG",
            kline_action in ("BUY", "INCREASE"),
        ])
        bearish_signals = sum([
            tech_score < 40,
            fund_score < 40,
            kline_dir == "SHORT",
            kline_action in ("SELL", "EMPTY"),
        ])

        if bullish_signals >= 3:
            direction, action = "LONG", "BUY"
        elif bearish_signals >= 3:
            direction, action = "SHORT", "SELL"
        elif bullish_signals >= 2 and composite > 60:
            direction, action = "LONG", "BUY"
        else:
            direction, action = "NEUTRAL", "HOLD"

        # 仓位计算
        if action == "HOLD":
            position_pct = 0.0
        elif confidence >= 75:
            position_pct = 0.15
        elif confidence >= 60:
            position_pct = 0.10
        else:
            position_pct = 0.05

        # 价格计算
        entry_price = price
        stop_loss = None
        take_profit = None
        if price and action in ("BUY", "SELL"):
            if direction == "LONG":
                stop_loss = round(price * 0.95, 2)
                take_profit = round(price * 1.10, 2)
            else:
                stop_loss = round(price * 1.05, 2)
                take_profit = round(price * 0.90, 2)

        risk_level = "HIGH" if confidence < 40 else "LOW" if confidence > 70 else "MEDIUM"

        factors = []
        factors.append(f"技术面评分 {tech_score}")
        factors.append(f"基本面评分 {fund_score}")
        factors.append(f"K线趋势 {kline_dir}")

        reasoning = f"综合评分 {composite:.0f}，技术面 {tech_score}，基本面 {fund_score}，K线 {kline_dir}。"
        if action == "HOLD":
            reasoning += "信号不一致，建议观望。"
        elif action == "BUY":
            reasoning += f"多维信号偏多，建议入场。"
        else:
            reasoning += f"多维信号偏空，建议规避。"

        return {
            "direction": direction,
            "confidence": confidence,
            "action": action,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_pct": position_pct,
            "reasoning": reasoning + " [规则引擎]",
            "risk_level": risk_level,
            "key_factors": factors,
        }

    # ------------------------------------------------------------------
    # 3. 智能执行
    # ------------------------------------------------------------------

    async def execute_decision(
        self,
        symbol: str,
        decision: Dict[str, Any],
        account_id: Optional[str] = None,
        execution_mode: str = "LIMIT",
    ) -> Dict[str, Any]:
        """
        根据 AI 决策执行交易。

        execution_mode:
          - LIMIT: 限价单
          - MARKET: 市价单
          - PLAN: 仅创建交易计划（不立即执行）
        """
        account_id = account_id or settings.TIGER_ACCOUNT
        action = decision.get("action", "HOLD")

        if action in ("HOLD", "AVOID"):
            return {
                "status": "skipped",
                "symbol": symbol,
                "message": f"AI 建议 {action}，未执行交易",
            }

        equity = await self._safe_get_equity(account_id)
        price = decision.get("entry_price") or await self._safe_get_price(symbol)

        if not price:
            execution_mode = "MARKET"

        # 计算数量
        position_pct = decision.get("position_pct", 0.10)
        if price and price > 0:
            position_value = equity * position_pct
            quantity = int(position_value / price)
        else:
            quantity = 0

        if quantity <= 0 and execution_mode != "PLAN":
            return {
                "status": "error",
                "symbol": symbol,
                "message": "计算数量为0，无法执行",
            }

        direction = decision.get("direction", "LONG")
        stop_loss = decision.get("stop_loss")
        take_profit = decision.get("take_profit")

        if execution_mode == "PLAN":
            # 创建交易计划
            plan_svc = TradingPlanService(self.session)
            plan = await plan_svc.create_plan(
                account_id=account_id,
                symbol=symbol,
                entry_price=Decimal(str(price)) if price else Decimal("0"),
                stop_loss=Decimal(str(stop_loss)) if stop_loss else Decimal("0"),
                take_profit=Decimal(str(take_profit)) if take_profit else Decimal("0"),
                target_position=Decimal(str(position_pct)),
                notes=f"AI决策: {decision.get('reasoning', '')}",
            )
            return {
                "status": "plan_created",
                "symbol": symbol,
                "plan_id": plan.id,
                "message": f"交易计划已创建 (ID: {plan.id})",
                "quantity": quantity,
                "direction": direction,
            }

        # 创建交易信号并执行
        signal = TradingSignal(
            signal_id=str(uuid.uuid4()),
            symbol=symbol,
            signal_type=SignalType.ENTRY,
            direction=direction,
            action="BUY" if direction == "LONG" else "SELL",
            price=Decimal(str(price)) if price else None,
            quantity=quantity,
            stop_loss=Decimal(str(stop_loss)) if stop_loss else None,
            take_profit=Decimal(str(take_profit)) if take_profit else None,
            confidence=decision.get("confidence", 50) / 100.0,
            source=SignalSource.STRATEGY_SCREEN,
            status=SignalStatus.PENDING,
            notes=f"AI决策: {decision.get('reasoning', '')}",
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(signal)
        await self.session.flush()

        try:
            executor = OrderExecutor(self.session)
            result = await executor._execute_single_signal(signal)
            return {
                "status": "executed",
                "symbol": symbol,
                "signal_id": signal.signal_id,
                "order_id": result.get("order_id"),
                "quantity": quantity,
                "direction": direction,
                "price": price,
                "message": f"订单已提交: {quantity}股 {symbol} @ ${price or 'MKT'}",
            }
        except Exception as e:
            logger.error(f"执行 {symbol} 失败: {e}")
            signal.status = SignalStatus.FAILED
            signal.notes = f"执行失败: {str(e)}"
            return {
                "status": "error",
                "symbol": symbol,
                "signal_id": signal.signal_id,
                "message": f"执行失败: {str(e)}",
            }

    async def batch_execute(
        self,
        decisions: List[Dict[str, Any]],
        account_id: Optional[str] = None,
        execution_mode: str = "LIMIT",
    ) -> Dict[str, Any]:
        """批量执行 AI 决策"""
        results = []
        success = 0
        failed = 0

        for item in decisions:
            symbol = item["symbol"]
            decision = item["decision"]
            try:
                result = await self.execute_decision(
                    symbol=symbol,
                    decision=decision,
                    account_id=account_id,
                    execution_mode=execution_mode,
                )
                results.append(result)
                if result["status"] in ("executed", "plan_created"):
                    success += 1
                elif result["status"] == "error":
                    failed += 1
            except Exception as e:
                failed += 1
                results.append({
                    "status": "error",
                    "symbol": symbol,
                    "message": str(e),
                })

        return {
            "total": len(decisions),
            "success": success,
            "failed": failed,
            "skipped": len(decisions) - success - failed,
            "results": results,
        }

    # ------------------------------------------------------------------
    # 数据获取辅助方法（带容错）
    # ------------------------------------------------------------------

    async def _safe_get_price(self, symbol: str) -> Optional[float]:
        try:
            return await self.market_data.get_current_price(symbol)
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格失败: {e}")
            return None

    async def _safe_get_technical(self, symbol: str) -> Dict[str, Any]:
        """获取技术面分析（返回 TechnicalAnalysisDTO — Pydantic 模型）"""
        try:
            from app.services.technical_analysis_service import TechnicalAnalysisService
            svc = TechnicalAnalysisService(self.session)
            result = await svc.get_technical_analysis(symbol)
            # result 是 TechnicalAnalysisDTO (Pydantic BaseModel)
            return {
                "score": result.trend_strength,
                "trend": result.trend_direction,
                "trend_strength": result.trend_strength,
                "rsi": result.rsi.value if result.rsi else None,
                "macd_signal": result.macd.status if result.macd else None,
                "support": result.support_levels[0] if result.support_levels else None,
                "resistance": result.resistance_levels[0] if result.resistance_levels else None,
                "summary": result.ai_summary or "",
            }
        except Exception as e:
            logger.warning(f"技术面分析 {symbol} 失败: {e}")
            return {"score": None, "trend": None, "summary": f"分析失败: {str(e)[:50]}"}

    async def _safe_get_fundamental(self, symbol: str) -> Dict[str, Any]:
        """获取基本面分析（返回 SimpleNamespace 或 None）"""
        try:
            from app.services.fundamental_analysis_service import FundamentalAnalysisService
            svc = FundamentalAnalysisService()
            result = await svc.get_fundamental_data(symbol)
            if result is None:
                return {"score": None, "summary": "无基本面数据"}
            # result 是 types.SimpleNamespace，用 getattr 访问
            return {
                "score": getattr(result, "overall_score", None),
                "pe_ratio": getattr(result, "pe_ratio", None),
                "roe": getattr(result, "roe", None),
                "revenue_growth": getattr(result, "revenue_growth", None),
                "debt_to_equity": getattr(result, "debt_to_equity", None),
                "summary": "",
            }
        except Exception as e:
            logger.warning(f"基本面分析 {symbol} 失败: {e}")
            return {"score": None, "summary": f"分析失败: {str(e)[:50]}"}

    async def _safe_get_kline_analysis(self, symbol: str) -> Dict[str, Any]:
        """获取K线走势分析"""
        try:
            from app.services.ai_advice_service import AiAdviceService
            svc = AiAdviceService(self.session)
            result = await svc.analyze_stock_kline(symbol)
            return {
                "direction": result.direction,
                "action": result.action,
                "prediction": result.prediction,
                "suggestion": result.suggestion,
                "details": result.details,
            }
        except Exception as e:
            logger.warning(f"K线分析 {symbol} 失败: {e}")
            return {"direction": None, "action": None, "prediction": "", "suggestion": ""}

    # ------------------------------------------------------------------
    # 评估历史持久化
    # ------------------------------------------------------------------

    async def _save_evaluation_history(
        self,
        evaluations: List[Dict[str, Any]],
        account_id: str,
    ):
        """保存评估历史到数据库（UPSERT：以 account_id + symbol 为主键，存在则更新）"""
        from sqlalchemy import select
        from sqlalchemy.dialects.mysql import insert
        
        try:
            for ev in evaluations:
                if ev.get("status") == "error":
                    continue  # 跳过失败的评估
                
                decision = ev.get("decision", {})
                dimensions = ev.get("dimensions", {})
                symbol = ev.get("symbol")
                
                # 构建数据字典
                data = dict(
                    account_id=account_id,
                    symbol=symbol,
                    current_price=ev.get("current_price"),
                    
                    # AI 决策核心字段
                    direction=decision.get("direction"),
                    confidence=decision.get("confidence"),
                    action=decision.get("action"),
                    entry_price=decision.get("entry_price"),
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit"),
                    position_pct=decision.get("position_pct"),
                    risk_level=decision.get("risk_level"),
                    reasoning=decision.get("reasoning"),
                    key_factors=decision.get("key_factors"),
                    
                    # 华尔街增强字段
                    risk_reward_ratio=decision.get("risk_reward_ratio"),
                    scenarios=decision.get("scenarios"),
                    catalysts=decision.get("catalysts"),
                    holding_period=decision.get("holding_period"),
                    
                    # 多维评分
                    dimensions=dimensions,
                )
                
                # MySQL UPSERT: INSERT ... ON DUPLICATE KEY UPDATE
                stmt = insert(AIEvaluationHistory).values(**data)
                
                # 定义更新字段（除主键和唯一键外的所有字段）
                update_dict = {k: v for k, v in data.items() if k not in ["account_id", "symbol"]}
                stmt = stmt.on_duplicate_key_update(**update_dict)
                
                await self.session.execute(stmt)
            
            await self.session.commit()
            logger.info(f"已保存/更新评估历史，共 {len([e for e in evaluations if e.get('status') != 'error'])} 条")
        except Exception as e:
            logger.error(f"保存评估历史失败: {e}")
            await self.session.rollback()

    async def get_evaluation_history(
        self,
        account_id: str,
        limit: int = 50,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取评估历史记录"""
        from sqlalchemy import select, desc
        
        query = select(AIEvaluationHistory).where(
            AIEvaluationHistory.account_id == account_id
        )
        
        if symbol:
            query = query.where(AIEvaluationHistory.symbol == symbol)
        
        query = query.order_by(desc(AIEvaluationHistory.created_at)).limit(limit)
        
        result = await self.session.execute(query)
        records = result.scalars().all()
        
        history_list = []
        for record in records:
            history_list.append({
                "id": record.id,
                "symbol": record.symbol,
                "current_price": float(record.current_price) if record.current_price else None,
                "direction": record.direction,
                "confidence": record.confidence,
                "action": record.action,
                "entry_price": float(record.entry_price) if record.entry_price else None,
                "stop_loss": float(record.stop_loss) if record.stop_loss else None,
                "take_profit": float(record.take_profit) if record.take_profit else None,
                "position_pct": float(record.position_pct) if record.position_pct else None,
                "risk_level": record.risk_level,
                "reasoning": record.reasoning,
                "key_factors": record.key_factors,
                "risk_reward_ratio": record.risk_reward_ratio,
                "scenarios": record.scenarios,
                "catalysts": record.catalysts,
                "holding_period": record.holding_period,
                "dimensions": record.dimensions,
                "created_at": record.created_at.isoformat() if record.created_at else None,
            })
        
        return history_list

    async def delete_evaluation_record(self, record_id: int, account_id: str) -> bool:
        """删除评估记录"""
        from sqlalchemy import delete
        
        try:
            stmt = delete(AIEvaluationHistory).where(
                AIEvaluationHistory.id == record_id,
                AIEvaluationHistory.account_id == account_id,
            )
            result = await self.session.execute(stmt)
            await self.session.commit()
            
            if result.rowcount > 0:
                logger.info(f"已删除评估记录 ID: {record_id}")
                return True
            else:
                logger.warning(f"评估记录不存在或无权删除: {record_id}")
                return False
        except Exception as e:
            logger.error(f"删除评估记录失败: {e}")
            await self.session.rollback()
            return False



    async def _safe_get_equity(self, account_id: str) -> float:
        """获取账户权益"""
        try:
            equity = await self.broker.get_account_equity(account_id)
            return float(equity) if equity else 100000.0
        except Exception as e:
            logger.warning(f"获取账户权益失败: {e}")
            return 100000.0
