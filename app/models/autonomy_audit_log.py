"""V10: AI 自主决策审计日志模型"""
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, DECIMAL, JSON, Text, text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class AutonomyAuditLog(Base):
    __tablename__ = "autonomy_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(16), nullable=False, comment="FULL/SEMI/ADVISORY")
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="BUY/SELL/HOLD/REBALANCE/REJECT")
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ai_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="AI 决策推理")
    confidence_score: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    risk_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    risk_gate_detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="实际下单 order_id / paper_trade_id")
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    circuit_breaker_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_autonomy_account_time", "account_id", "created_at"),
        Index("idx_autonomy_decision_type", "decision_type"),
    )
