from datetime import datetime
from decimal import Decimal
from typing import Optional, Any
from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, JSON, SmallInteger, Text, text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class TradingPlan(Base):
    __tablename__ = "trading_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(16), nullable=False, default="MANUAL")

    entry_price: Mapped[Decimal] = mapped_column(DECIMAL(20, 6), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(DECIMAL(20, 6), nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(DECIMAL(20, 6), nullable=False)
    target_position: Mapped[Decimal] = mapped_column(DECIMAL(10, 4), nullable=False)

    plan_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    plan_tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))

    # ── V10.3: 交易可观测性字段 ────────────────────────────────────────────────
    direction: Mapped[Optional[str]] = mapped_column(String(4), nullable=True, comment="BUY/SELL")
    confidence: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2), nullable=True, comment="AI置信度 0-100")
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="AI决策摘要")
    autonomy_action: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="AUTO_EXECUTE/PENDING_CONFIRM")
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="AI_AUTONOMOUS/AI_ADVISORY/MANUAL")
    pipeline_stage: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True, comment="当前Pipeline阶段 0-16")
    stage_entered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="进入当前阶段时间")
    stage_history: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="阶段历史 [{stage,entered_at,exited_at}]")
    provenance_snapshot: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="决策溯源快照")
    position_fsm_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="关联持仓FSM最新状态")

    __table_args__ = (
        Index("idx_plan_account_status", "account_id", "plan_status"),
        Index("idx_plan_symbol", "symbol"),
        Index("idx_plan_valid_until", "valid_until"),
        Index("idx_plan_pipeline_stage", "pipeline_stage"),
        Index("idx_plan_direction", "direction"),
        Index("idx_plan_source", "source"),
    )
