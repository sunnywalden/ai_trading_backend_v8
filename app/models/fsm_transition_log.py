"""V10.3: FSM 状态转换事件日志模型"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import Integer, String, DateTime, DECIMAL, Text, SmallInteger, text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class FsmTransitionLog(Base):
    __tablename__ = "fsm_transition_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="关联 trading_plan.id")
    fsm_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="PLAN / POSITION")
    from_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    engine: Mapped[Optional[str]] = mapped_column(String(32), nullable=True,
                                                   comment="scale_in/scale_out/trailing/manual")
    qty_delta: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 4), nullable=True)
    trigger_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        Index("idx_fsm_plan_id", "plan_id"),
        Index("idx_fsm_type", "fsm_type"),
        Index("idx_fsm_occurred_at", "occurred_at"),
    )
