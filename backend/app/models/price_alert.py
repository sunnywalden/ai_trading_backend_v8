"""V9: 价格告警模型"""
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, DECIMAL, Boolean, text, Index
from app.models.db import Base


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    condition_type = Column(String(32), nullable=False)
    threshold = Column(DECIMAL(20, 6), nullable=False)
    action = Column(String(16), nullable=False, default="notify")
    linked_plan_id = Column(Integer, nullable=True)
    alert_status = Column(String(16), nullable=False, default="ACTIVE")
    triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_alert_account_status", "account_id", "alert_status"),
        Index("idx_alert_symbol", "symbol"),
    )


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    alert_id = Column(BigInteger, nullable=False)
    account_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    trigger_price = Column(DECIMAL(20, 6), nullable=False)
    trigger_time = Column(DateTime, nullable=False)
    notification_sent = Column(Boolean, nullable=False, default=False)
    action_taken = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_alert_hist_account_time", "account_id", "trigger_time"),
        Index("idx_alert_hist_alert", "alert_id"),
    )
