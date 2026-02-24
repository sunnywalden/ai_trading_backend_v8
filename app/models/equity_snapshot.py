"""V9: 账户权益快照模型"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, DECIMAL, text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_equity: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False)
    cash: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False, default=0)
    market_value: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False, default=0)
    realized_pnl: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False, default=0)
    daily_return: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    cumulative_return: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    max_drawdown_pct: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    benchmark_return: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uk_account_date"),
        Index("idx_equity_account_date", "account_id", "snapshot_date"),
    )
