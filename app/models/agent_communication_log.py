"""agent_communication_log — V10.3.3 多智能体通信日志

记录 MultiAgentOrchestrator 中各 Agent 的每条消息，支持完整的 Agent 对话回溯。
"""

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Float, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class AgentCommunicationLog(Base):
    """多 Agent 消息记录————含 run_id 批次标记，支持按次对话回溯。"""

    __tablename__ = "agent_communication_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="同一次 orchestration 共享 run_id（UUID）")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Agent 标识
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="如 MarketAnalystAgent / RiskChallengerAgent 等")
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False, comment="market_analyst / risk_challenger / execution_optimizer / researcher / orchestrator")
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="本次 run 中消息顺序号")

    # 消息内容
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="ANALYSIS/CHALLENGE/DECISION/SUMMARY/TOOL_CALL")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Agent 对本消息置信度 0~1")

    # 结构化输出（可选）
    structured_output: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="结构化输出 JSON，如 challenge_points[]")
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="工具调用记录")

    # 上下文
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="触发源，如 signal_id / intent_id / manual")

    # LLM 元数据
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_acl_run_seq", "run_id", "sequence"),
        Index("idx_acl_user_created", "user_id", "created_at"),
        {"comment": "多智能体通信日志 V10.3.3"},
    )
