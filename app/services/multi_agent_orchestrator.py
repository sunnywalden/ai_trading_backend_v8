"""multi_agent_orchestrator.py — V10.3.3 多智能体协作框架

五专职 Agent：
  1. MarketAnalystAgent    - 市场行情与趋势综合分析
  2. RiskChallengerAgent   - 强制反驳 BUY 信号，输出 challenge_points
  3. ExecutionOptimizerAgent - 执行策略优化建议（algo/timing）
  4. ResearchAgent         - 深度基本面/量化研究
  5. OrchestratorAgent     - 综合所有输入 → 最终决策

所有消息写入 agent_communication_log。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_communication_log import AgentCommunicationLog

logger = logging.getLogger(__name__)


# ─── Pydantic Schema ──────────────────────────────────────────────────────────

class AgentMessage(BaseModel):
    """单条 Agent 消息。"""
    agent_id: str
    role: str                      # market_analyst / risk_challenger …
    message_type: str              # ANALYSIS / CHALLENGE / DECISION / SUMMARY
    content: str
    confidence: float | None = None
    structured_output: dict | None = None


class OrchestratorResult(BaseModel):
    """一次 Orchestration 运行结果。"""
    run_id: str
    symbol: str
    final_decision: str            # BUY / SELL / HOLD
    final_confidence: float
    orchestrator_summary: str
    challenge_points: list[str]    # RiskChallengerAgent 的反驳要点
    messages: list[AgentMessage]
    latency_ms: int


# ─── Agent 实现 ──────────────────────────────────────────────────────────────

class _BaseAgent:
    agent_id: str = "base"
    role: str = "base"
    model: str = "deepseek-chat"

    async def _call_llm(self, prompt: str, system: str = "") -> tuple[str, int]:
        """内部 LLM 调用，返回 (content, tokens_used)。"""
        from app.services.ai_client import call_ai  # 懒加载，避免循环
        try:
            resp = await call_ai(
                model=self.model,
                messages=[
                    {"role": "system", "content": system or "You are a professional quantitative analyst."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
            )
            content = resp.get("content", "")
            tokens = resp.get("usage", {}).get("total_tokens", 0)
            return content, tokens
        except Exception as e:
            logger.error("%s LLM call failed: %s", self.agent_id, e)
            return f"[ERROR: {e}]", 0


class MarketAnalystAgent(_BaseAgent):
    agent_id = "MarketAnalystAgent"
    role = "market_analyst"

    async def analyze(self, symbol: str, context: dict) -> AgentMessage:
        prompt = (
            f"Analyze {symbol} for a potential trade. "
            f"Current context: {context}. "
            "Provide: 1) trend direction 2) key support/resistance 3) volume analysis "
            "4) sector momentum 5) overall recommendation (BUY/SELL/HOLD) with confidence 0-1."
        )
        content, _ = await self._call_llm(prompt, "You are a expert sell-side market analyst.")
        return AgentMessage(
            agent_id=self.agent_id,
            role=self.role,
            message_type="ANALYSIS",
            content=content,
            confidence=0.7,
        )


class RiskChallengerAgent(_BaseAgent):
    agent_id = "RiskChallengerAgent"
    role = "risk_challenger"
    model = "deepseek-reasoner"

    async def challenge(self, symbol: str, analyst_view: str) -> AgentMessage:
        """必须输出 challenge_points 列表。"""
        prompt = (
            f"Act as a devil's advocate risk manager. The market analyst recommends a BUY for {symbol}. "
            f"Analyst reasoning: {analyst_view}\n\n"
            "List 3-5 specific risk factors and counter-arguments in JSON format: "
            '{"challenge_points": ["risk1", "risk2", ...], "overall_risk_level": "HIGH|MEDIUM|LOW", '
            '"veto_recommendation": true|false}'
        )
        content, tokens = await self._call_llm(prompt, "You are a rigorous quantitative risk challenger. Be skeptical.")
        # 尝试解析结构化输出
        structured = None
        try:
            import json
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                structured = json.loads(content[start:end])
        except Exception:
            structured = {"challenge_points": [content[:200]], "overall_risk_level": "MEDIUM", "veto_recommendation": False}

        return AgentMessage(
            agent_id=self.agent_id,
            role=self.role,
            message_type="CHALLENGE",
            content=content,
            confidence=0.8,
            structured_output=structured,
        )


class ExecutionOptimizerAgent(_BaseAgent):
    agent_id = "ExecutionOptimizerAgent"
    role = "execution_optimizer"

    async def optimize(self, symbol: str, size_usd: float, market_data: dict) -> AgentMessage:
        prompt = (
            f"Optimize execution strategy for {symbol} order of ${size_usd:,.0f}. "
            f"Market data: {market_data}. "
            "Recommend: 1) algo type (TWAP/VWAP/LIMIT/MARKET) "
            "2) optimal execution window (e.g. first 30min, last 1h) "
            "3) suggested limit price offset (bps) "
            "4) expected IS cost estimate (bps). Output JSON."
        )
        content, _ = await self._call_llm(prompt, "You are a TCA expert focused on minimizing execution costs.")
        return AgentMessage(
            agent_id=self.agent_id,
            role=self.role,
            message_type="ANALYSIS",
            content=content,
            confidence=0.75,
        )


class ResearchAgent(_BaseAgent):
    agent_id = "ResearchAgent"
    role = "researcher"
    model = "deepseek-reasoner"

    async def research(self, symbol: str) -> AgentMessage:
        prompt = (
            f"Deep research on {symbol}: "
            "1) Recent fundamental changes (earnings, guidance) "
            "2) Insider activity and institutional positioning "
            "3) Competitive dynamics "
            "4) Key risks not priced in "
            "5) Quantitative momentum & mean-reversion signals. "
            "Be concise but insightful."
        )
        content, _ = await self._call_llm(prompt, "You are a buy-side equity research analyst.")
        return AgentMessage(
            agent_id=self.agent_id,
            role=self.role,
            message_type="ANALYSIS",
            content=content,
            confidence=0.65,
        )


class OrchestratorAgent(_BaseAgent):
    agent_id = "OrchestratorAgent"
    role = "orchestrator"
    model = "deepseek-reasoner"

    async def orchestrate(
        self,
        symbol: str,
        analyst_view: str,
        challenge_points: list[str],
        research_summary: str,
        exec_recommendation: str,
    ) -> AgentMessage:
        prompt = (
            f"As the head portfolio manager, synthesize these inputs for {symbol}:\n\n"
            f"MARKET ANALYST: {analyst_view[:500]}\n\n"
            f"RISK CHALLENGER: {challenge_points}\n\n"
            f"RESEARCH: {research_summary[:500]}\n\n"
            f"EXECUTION: {exec_recommendation[:300]}\n\n"
            "Output your FINAL DECISION as JSON: "
            '{"decision": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "rationale": "...", '
            '"position_size_pct": 0-100, "stop_loss_pct": -1 to 0, "take_profit_pct": 0 to 100}'
        )
        content, tokens = await self._call_llm(
            prompt,
            "You are the chief investment officer. Make final portfolio decisions.",
        )
        structured = None
        try:
            import json
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                structured = json.loads(content[start:end])
        except Exception:
            structured = {"decision": "HOLD", "confidence": 0.5, "rationale": content[:200]}

        return AgentMessage(
            agent_id=self.agent_id,
            role=self.role,
            message_type="DECISION",
            content=content,
            confidence=structured.get("confidence", 0.5) if structured else 0.5,
            structured_output=structured,
        )


# ─── Orchestrator ────────────────────────────────────────────────────────────

class MultiAgentOrchestrator:
    """协调五个 Agent 完成一次完整的投资决策流程。"""

    def __init__(self):
        self.market_analyst = MarketAnalystAgent()
        self.risk_challenger = RiskChallengerAgent()
        self.exec_optimizer = ExecutionOptimizerAgent()
        self.researcher = ResearchAgent()
        self.orchestrator_agent = OrchestratorAgent()

    async def run(
        self,
        db: AsyncSession,
        user_id: str,
        symbol: str,
        context: dict | None = None,
        size_usd: float = 10000.0,
    ) -> OrchestratorResult:
        """执行完整的五智能体协作流程。"""
        run_id = str(uuid.uuid4())
        t_start = time.time()
        context = context or {}
        all_messages: list[AgentMessage] = []

        logger.info("MultiAgentOrchestrator: run_id=%s symbol=%s", run_id, symbol)

        # Step 1: 并行 - 市场分析 + 深度研究
        analyst_msg, research_msg = await asyncio.gather(
            self.market_analyst.analyze(symbol, context),
            self.researcher.research(symbol),
        )
        all_messages.extend([analyst_msg, research_msg])

        # Step 2: 并行 - 风险挑战 + 执行优化 (依赖 analyst_view)
        challenger_msg, exec_msg = await asyncio.gather(
            self.risk_challenger.challenge(symbol, analyst_msg.content),
            self.exec_optimizer.optimize(symbol, size_usd, context),
        )
        all_messages.extend([challenger_msg, exec_msg])

        # Step 3: Orchestrator 综合决策
        challenge_points = (
            (challenger_msg.structured_output or {}).get("challenge_points", [])
            if challenger_msg.structured_output else []
        )
        orch_msg = await self.orchestrator_agent.orchestrate(
            symbol,
            analyst_msg.content,
            challenge_points,
            research_msg.content,
            exec_msg.content,
        )
        all_messages.append(orch_msg)

        final_so = orch_msg.structured_output or {}
        final_decision = final_so.get("decision", "HOLD")
        final_confidence = float(final_so.get("confidence", 0.5))

        # 写入 DB
        await _persist_messages(db, run_id, user_id, symbol, all_messages)

        latency_ms = int((time.time() - t_start) * 1000)
        return OrchestratorResult(
            run_id=run_id,
            symbol=symbol,
            final_decision=final_decision,
            final_confidence=final_confidence,
            orchestrator_summary=orch_msg.content[:1000],
            challenge_points=challenge_points,
            messages=all_messages,
            latency_ms=latency_ms,
        )

    async def get_run_summary(
        self, db: AsyncSession, run_id: str
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        stmt = (
            select(AgentCommunicationLog)
            .where(AgentCommunicationLog.run_id == run_id)
            .order_by(AgentCommunicationLog.sequence)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "sequence": r.sequence,
                "agent_id": r.agent_id,
                "role": r.agent_role,
                "message_type": r.message_type,
                "content": r.content[:500],
                "confidence": r.confidence,
                "structured_output": r.structured_output,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def list_runs(
        self, db: AsyncSession, user_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """列出历史 run，每个 run 只返回 orchestrator 最终决策行。"""
        from sqlalchemy import select
        stmt = (
            select(AgentCommunicationLog)
            .where(
                AgentCommunicationLog.user_id == user_id,
                AgentCommunicationLog.agent_id == "OrchestratorAgent",
            )
            .order_by(AgentCommunicationLog.created_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "run_id": r.run_id,
                "symbol": r.symbol,
                "decision": (r.structured_output or {}).get("decision", "HOLD"),
                "confidence": r.confidence,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


async def _persist_messages(
    db: AsyncSession,
    run_id: str,
    user_id: str,
    symbol: str,
    messages: list[AgentMessage],
) -> None:
    for seq, msg in enumerate(messages):
        log = AgentCommunicationLog(
            run_id=run_id,
            user_id=user_id,
            symbol=symbol,
            agent_id=msg.agent_id,
            agent_role=msg.role,
            sequence=seq,
            message_type=msg.message_type,
            content=msg.content,
            confidence=msg.confidence,
            structured_output=msg.structured_output,
        )
        db.add(log)
    await db.flush()


multi_agent_orchestrator = MultiAgentOrchestrator()
