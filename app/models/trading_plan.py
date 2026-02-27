from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, JSON, text, Index
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

    __table_args__ = (
        Index("idx_plan_account_status", "account_id", "plan_status"),
        Index("idx_plan_symbol", "symbol"),
        Index("idx_plan_valid_until", "valid_until"),
    )
