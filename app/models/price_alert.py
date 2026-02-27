"""V9: 价格告警模型"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, DECIMAL, Boolean, text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(DECIMAL(20, 6), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="notify")
    linked_plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    alert_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_alert_account_status", "account_id", "alert_status"),
        Index("idx_alert_symbol", "symbol"),
    )


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_price: Mapped[Decimal] = mapped_column(DECIMAL(20, 6), nullable=False)
    trigger_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notification_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action_taken: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_alert_hist_account_time", "account_id", "trigger_time"),
        Index("idx_alert_hist_alert", "alert_id"),
    )
