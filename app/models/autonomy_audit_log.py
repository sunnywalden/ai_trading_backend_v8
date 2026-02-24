"""V10: AI 自主决策审计日志模型"""
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, DECIMAL, JSON, Text, text, Index
from app.models.db import Base


class AutonomyAuditLog(Base):
    __tablename__ = "autonomy_audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    autonomy_level = Column(String(16), nullable=False, comment="FULL/SEMI/ADVISORY")
    decision_type = Column(String(32), nullable=False, comment="BUY/SELL/HOLD/REBALANCE/REJECT")
    symbol = Column(String(32), nullable=True)
    ai_reasoning = Column(Text, nullable=True, comment="AI 决策推理")
    confidence_score = Column(DECIMAL(5, 2), nullable=True)
    risk_gate_passed = Column(Boolean, nullable=False)
    risk_gate_detail = Column(JSON, nullable=True)
    order_id = Column(String(64), nullable=True, comment="实际下单 order_id / paper_trade_id")
    revoked_at = Column(DateTime, nullable=True)
    revoke_reason = Column(Text, nullable=True)
    circuit_breaker_triggered = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_autonomy_account_time", "account_id", "created_at"),
        Index("idx_autonomy_decision_type", "decision_type"),
    )
