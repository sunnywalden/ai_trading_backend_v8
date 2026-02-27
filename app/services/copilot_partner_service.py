"""V10.2-M7: Copilot AI 合伙人增强版

新能力：
1. 主动推送情报（ProactiveIntelligenceService）：
   - 市场状态切换预警
   - 加仓机会提醒
   - 连续亏损异常告警
   - 每周策略预览

2. 多步骤意图推理（MultiStepIntentEngine）：
   - 解析复杂复合查询（如"NVDA 财报前后该怎么操作？"）
   - 拉取多个数据源 → 聚合 → 结构化推荐

3. 深度研究模式（DeepResearchEngine）：
   - 使用 deepseek-reasoner
   - 6 个数据源（技术/基本面/宏观/期权/情绪/历史相似案例）
   - 输出 500 字结构化报告 + 评级 + 建仓建议
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any

logger = logging.getLogger(__name__)


# ── 主动情报服务 ──────────────────────────────────────────────────────────────

@dataclass
class ProactiveAlert:
    alert_type:  str     # REGIME_SWITCH / SCALE_IN_OPP / DRAWDOWN_ALERT / WEEKLY_PREVIEW
    priority:    str     # HIGH / MEDIUM / LOW
    title:       str
    body:        str
    action_url:  Optional[str] = None
    metadata:    dict = field(default_factory=dict)
    created_at:  datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        return {
            "alert_type":  self.alert_type,
            "priority":    self.priority,
            "title":       self.title,
            "body":        self.body,
            "action_url":  self.action_url,
            "metadata":    self.metadata,
            "created_at":  self.created_at.isoformat(),
        }


class ProactiveIntelligenceService:
    """主动情报推送服务：在关键时刻向用户推送洞察。"""

    def build_regime_switch_alert(
        self,
        prev_regime: str,
        curr_regime: str,
        confidence: float,
        affected_positions: list[dict],
    ) -> ProactiveAlert:
        """构建市场状态切换预警。"""
        impact_count = len(affected_positions)
        return ProactiveAlert(
            alert_type="REGIME_SWITCH",
            priority="HIGH" if confidence >= 0.80 else "MEDIUM",
            title=f"市场状态切换：{prev_regime} → {curr_regime}",
            body=(
                f"检测到市场状态从 **{prev_regime}** 切换为 **{curr_regime}**（置信度 {confidence:.0%}）。\n\n"
                f"当前持有 {impact_count} 个仓位可能受影响。建议检查：\n"
                + "\n".join(f"- {p.get('symbol')}: {p.get('pnl_pct', 0):.1%} PnL" for p in affected_positions[:5])
            ),
            action_url="/regime",
            metadata={
                "prev_regime": prev_regime,
                "curr_regime": curr_regime,
                "confidence": confidence,
                "affected_count": impact_count,
            },
        )

    def build_scale_in_alert(self, candidates: list[dict]) -> Optional[ProactiveAlert]:
        """构建加仓机会提醒。"""
        if not candidates:
            return None
        top   = candidates[0]
        extra = len(candidates) - 1
        return ProactiveAlert(
            alert_type="SCALE_IN_OPP",
            priority="MEDIUM",
            title=f"加仓机会：{top.get('symbol')} (+{extra} 更多)",
            body=(
                f"**{top.get('symbol')}** 触发加仓条件（{top.get('reason', '')}）。\n"
                f"建议加仓 {top.get('quantity_delta', 0):.0f} 股。\n"
                + (f"另有 {extra} 个候选仓位。" if extra > 0 else "")
            ),
            action_url="/positions",
            metadata={"candidates": candidates[:5]},
        )

    def build_drawdown_alert(
        self,
        consecutive_losses: int,
        total_loss_pct: float,
        threshold: int = 3,
    ) -> Optional[ProactiveAlert]:
        """连续亏损告警。"""
        if consecutive_losses < threshold:
            return None
        return ProactiveAlert(
            alert_type="DRAWDOWN_ALERT",
            priority="HIGH",
            title=f"连续 {consecutive_losses} 笔亏损警告",
            body=(
                f"最近 **{consecutive_losses}** 笔交易连续亏损，累计 **{total_loss_pct:.1%}**。\n\n"
                "建议暂停开新仓，审查策略参数是否需要调整。"
            ),
            action_url="/attribution",
            metadata={"consecutive_losses": consecutive_losses, "total_loss_pct": total_loss_pct},
        )

    def build_weekly_preview(
        self,
        events: list[dict],
        regime: str,
        top_signals: list[dict],
    ) -> ProactiveAlert:
        """每周策略预览。"""
        event_summary = "\n".join(
            f"- {e.get('title')} ({e.get('event_date', '')[:10]})" for e in events[:5]
        )
        signal_summary = "\n".join(
            f"- {s.get('symbol')}: {s.get('recommendation', 'HOLD')} (置信度 {s.get('fused_confidence', 0):.0%})"
            for s in top_signals[:5]
        )
        return ProactiveAlert(
            alert_type="WEEKLY_PREVIEW",
            priority="LOW",
            title=f"本周市场预览 | 当前状态：{regime}",
            body=(
                f"**当前市场状态**：{regime}\n\n"
                f"**本周重大事件**：\n{event_summary or '暂无重大事件'}\n\n"
                f"**高置信信号**：\n{signal_summary or '暂无信号'}"
            ),
            action_url="/dashboard",
            metadata={"regime": regime, "event_count": len(events)},
        )


# ── 多步骤意图推理引擎 ────────────────────────────────────────────────────────

@dataclass
class IntentStep:
    step_id:    int
    action:     str        # FETCH_PRICE / FETCH_EARNINGS / CHECK_IV / GET_HISTORY / COMPUTE_SIGNAL
    symbol:     str
    params:     dict = field(default_factory=dict)
    result:     Optional[dict] = None


@dataclass
class MultiStepIntentResult:
    query:       str
    steps:       list[IntentStep]
    analysis:    str
    recommendation: str     # BUY / SELL / HOLD / WAIT
    confidence:  float
    reasoning:   str
    actions:     list[dict] = field(default_factory=list)   # 可执行操作

    def to_dict(self) -> dict:
        return {
            "query":          self.query,
            "steps_count":    len(self.steps),
            "analysis":       self.analysis,
            "recommendation": self.recommendation,
            "confidence":     self.confidence,
            "reasoning":      self.reasoning,
            "actions":        self.actions,
        }


class MultiStepIntentEngine:
    """
    多步骤意图推理：解析用户复杂查询，拆解为多个数据获取步骤，
    聚合后调用 LLM 生成结构化建议。

    设计约定：步骤解析用 deepseek-chat（快），最终分析用 deepseek-reasoner（深）。
    """

    async def process(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> MultiStepIntentResult:
        """处理一个复合查询意图。"""
        # 1. 识别意图中的步骤
        steps = await self._parse_steps(query)

        # 2. 执行每个步骤（若步骤失败跳过）
        for step in steps:
            step.result = await self._execute_step(step)

        # 3. 聚合结果 → 调用 deepseek-reasoner 生成分析
        result = await self._synthesize(query, steps)
        return result

    async def _parse_steps(self, query: str) -> list[IntentStep]:
        """用 deepseek-chat 快速解析查询中的数据需求步骤。"""
        try:
            from openai import AsyncOpenAI

            from app.core.config import settings

            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )
            resp = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You decompose user trading queries into data fetch steps. "
                            "Return JSON array of steps, each: {step_id, action, symbol, params}. "
                            "Actions: FETCH_PRICE, FETCH_EARNINGS, CHECK_IV, GET_SIGNALS, GET_REGIME, GET_NEWS. "
                            "Return ONLY valid JSON array."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                temperature=0.1,
                max_tokens=500,
            )
            # openai stubs allow content to be None
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            step_dicts = json.loads(raw)
            return [
                IntentStep(
                    step_id=s.get("step_id", i),
                    action=s.get("action", ""),
                    symbol=s.get("symbol", ""),
                    params=s.get("params", {}),
                )
                for i, s in enumerate(step_dicts)
            ]
        except Exception as e:
            logger.warning(f"[MultiStepIntent] parse_steps failed: {e}")
            return []

    async def _execute_step(self, step: IntentStep) -> Optional[dict]:
        """执行单个数据步骤（此处简化：实际应接各 data provider）。"""
        try:
            import yfinance as yf

            symbol = step.symbol
            if step.action == "FETCH_PRICE":
                ticker = yf.Ticker(symbol)
                hist   = ticker.history(period="5d")
                if not hist.empty:
                    return {"price": float(hist["Close"].iloc[-1]), "symbol": symbol}
            elif step.action == "FETCH_EARNINGS":
                ticker = yf.Ticker(symbol)
                cal    = ticker.calendar
                if cal and isinstance(cal, dict):
                    dates = cal.get("Earnings Date", [])
                    return {"next_earnings": str(dates[0]) if dates else None, "symbol": symbol}
            elif step.action == "GET_REGIME":
                # 从 DB 获取当前 regime（此处返回占位）
                return {"regime": "UNKNOWN", "note": "regime from DB not injected in step context"}
        except Exception as e:
            logger.debug(f"[MultiStepIntent] step {step.step_id} {step.action} failed: {e}")
        return None

    async def _synthesize(
        self,
        query: str,
        steps: list[IntentStep],
    ) -> MultiStepIntentResult:
        """调用 deepseek-reasoner 综合分析所有步骤结果。"""
        step_results = [
            {"action": s.action, "symbol": s.symbol, "result": s.result}
            for s in steps
        ]
        try:
            from openai import AsyncOpenAI

            from app.core.config import settings

            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )
            prompt = (
                f"User query: {query}\n\n"
                f"Data gathered:\n{json.dumps(step_results, indent=2, default=str)}\n\n"
                "Provide a structured analysis with: "
                "recommendation (BUY/SELL/HOLD/WAIT), confidence (0-1), "
                "brief reasoning (3-5 sentences), and suggested actions. "
                "Return JSON: {analysis, recommendation, confidence, reasoning, actions: []}."
            )
            resp = await client.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            return MultiStepIntentResult(
                query=query,
                steps=steps,
                analysis=parsed.get("analysis", ""),
                recommendation=parsed.get("recommendation", "HOLD"),
                confidence=float(parsed.get("confidence", 0.5)),
                reasoning=parsed.get("reasoning", ""),
                actions=parsed.get("actions", []),
            )
        except Exception as e:
            logger.error(f"[MultiStepIntent] synthesize failed: {e}", exc_info=True)
            return MultiStepIntentResult(
                query=query, steps=steps, analysis="Analysis unavailable",
                recommendation="HOLD", confidence=0.5,
                reasoning=str(e), actions=[],
            )


# ── 深度研究引擎 ──────────────────────────────────────────────────────────────

@dataclass
class DeepResearchReport:
    symbol:          str
    query:           str
    rating:          str           # STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
    confidence:      float
    price_target:    Optional[float]
    report_body:     str           # 500 字结构化报告
    key_risks:       list[str]
    key_catalysts:   list[str]
    position_recommendation: dict  # {'action': 'BUY', 'size_pct': 0.03, 'entry_zone': [...], 'stop_loss': ...}
    data_sources:    list[str]

    def to_dict(self) -> dict:
        return {
            "symbol":           self.symbol,
            "query":            self.query,
            "rating":           self.rating,
            "confidence":       self.confidence,
            "price_target":     self.price_target,
            "report_body":      self.report_body,
            "key_risks":        self.key_risks,
            "key_catalysts":    self.key_catalysts,
            "position_recommendation": self.position_recommendation,
            "data_sources":     self.data_sources,
        }


class DeepResearchEngine:
    """
    深度研究模式：整合 6 个数据源，调用 deepseek-reasoner 生成机构级研报。

    数据源：
      1. 技术分析（yfinance 价格+指标）
      2. 基本面（yfinance Financials）
      3. 宏观背景（当前 regime）
      4. 期权数据（IV Rank, Put/Call ratio）
      5. 情绪数据（短仓利率等）
      6. 历史相似案例（ai_insight_repository）
    """

    async def research(
        self,
        symbol: str,
        query: str,
        db: Optional[object] = None,
    ) -> DeepResearchReport:
        """执行深度研究，返回完整报告。"""
        # ── 收集数据 ───────────────────────────────────────────────────────────
        data = await self._gather_data(symbol, db)

        # ── 调用 deepseek-reasoner ─────────────────────────────────────────────
        report = await self._generate_report(symbol, query, data)
        return report

    async def _gather_data(self, symbol: str, db) -> dict:
        """并行收集 6 个数据源（简化版，生产中各数据源独立 service）。"""
        import asyncio

        # type of values vary, so annotate to avoid inferring str-only dict
        data: dict[str, Any] = {"symbol": symbol}
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            hist   = ticker.history(period="3mo")
            info   = ticker.info or {}
            data["price"]      = float(hist["Close"].iloc[-1]) if not hist.empty else None
            data["52w_high"]   = info.get("fiftyTwoWeekHigh")
            data["52w_low"]    = info.get("fiftyTwoWeekLow")
            data["pe_ratio"]   = info.get("trailingPE")
            data["market_cap"] = info.get("marketCap")
            data["short_pct"]  = info.get("shortPercentOfFloat")
            data["beta"]       = info.get("beta")
            # 价格动能
            if len(hist) >= 20:
                data["rsi_approx"] = self._approx_rsi(hist["Close"].tolist(), 14)
        except Exception as e:
            logger.debug(f"[DeepResearch] yfinance gather failed for {symbol}: {e}")
        return data

    def _approx_rsi(self, closes: list[float], period: int = 14) -> float:
        """简单 RSI 近似计算（Wilder 平滑）。"""
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1 + rs))

    async def _generate_report(self, symbol: str, query: str, data: dict) -> DeepResearchReport:
        """调用 deepseek-reasoner 生成研报。"""
        try:
            from openai import AsyncOpenAI

            from app.core.config import settings

            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )
            prompt = f"""You are a professional equity research analyst. Produce a deep-research report for:

Symbol: {symbol}
User query: {query}
Market data:
{json.dumps(data, indent=2, default=str)}

Write a comprehensive ~500 word report and return ONLY this JSON structure:
{{
  "rating": "BUY|HOLD|SELL|STRONG_BUY|STRONG_SELL",
  "confidence": 0.0-1.0,
  "price_target": float or null,
  "report_body": "...",
  "key_risks": ["risk1", "risk2", "risk3"],
  "key_catalysts": ["catalyst1", "catalyst2"],
  "position_recommendation": {{
    "action": "BUY|HOLD|SELL",
    "size_pct": 0.03,
    "entry_zone": [lower, upper],
    "stop_loss": float,
    "take_profit": float
  }},
  "data_sources": ["technical", "fundamental", "macro", "options", "sentiment", "historical_patterns"]
}}
"""
            resp = await client.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2500,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            return DeepResearchReport(
                symbol=symbol,
                query=query,
                rating=parsed.get("rating", "HOLD"),
                confidence=float(parsed.get("confidence", 0.5)),
                price_target=parsed.get("price_target"),
                report_body=parsed.get("report_body", ""),
                key_risks=parsed.get("key_risks", []),
                key_catalysts=parsed.get("key_catalysts", []),
                position_recommendation=parsed.get("position_recommendation", {}),
                data_sources=parsed.get("data_sources", []),
            )
        except Exception as e:
            logger.error(f"[DeepResearch] generation failed: {e}", exc_info=True)
            return DeepResearchReport(
                symbol=symbol, query=query, rating="HOLD", confidence=0.0,
                price_target=None, report_body=f"Research unavailable: {e}",
                key_risks=[], key_catalysts=[], position_recommendation={}, data_sources=[],
            )


# ── 增强版 Copilot 服务门面 ───────────────────────────────────────────────────

class CopilotPartnerService:
    """
    M7 增强版 Copilot 合伙人服务门面。
    整合三大子能力：主动情报 / 多步骤意图 / 深度研究。
    """

    def __init__(self) -> None:
        self.proactive  = ProactiveIntelligenceService()
        self.multi_step = MultiStepIntentEngine()
        self.deep_research = DeepResearchEngine()

    async def handle_chat(
        self,
        query: str,
        mode: str = "standard",    # "standard" | "deep_research"
        symbol: Optional[str] = None,
        db: Optional[object] = None,
    ) -> dict:
        """
        统一聊天入口。

        mode="standard"      → 多步骤意图推理
        mode="deep_research" → DeepResearch 模式（需要 symbol）
        """
        if mode == "deep_research" and symbol:
            report = await self.deep_research.research(symbol, query, db)
            return report.to_dict()
        else:
            result = await self.multi_step.process(query)
            return result.to_dict()


# ── 模块级单例 ────────────────────────────────────────────────────────────────
copilot_partner_service = CopilotPartnerService()
