"""V9: 审计日志模型"""
from sqlalchemy import Column, BigInteger, String, DateTime, JSON, text, Index
from app.models.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False)
    resource = Column(String(128), nullable=False)
    payload = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "created_at"),
        Index("idx_audit_action", "action"),
    )
