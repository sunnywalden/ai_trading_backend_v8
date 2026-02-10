"""V9: 通知记录模型"""
from sqlalchemy import Column, BigInteger, String, DateTime, Text, text, Index
from app.models.db import Base


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    channel = Column(String(16), nullable=False)
    event_type = Column(String(32), nullable=False)
    title = Column(String(128), nullable=False)
    body = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="SENT")
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_notif_account_time", "account_id", "created_at"),
    )
