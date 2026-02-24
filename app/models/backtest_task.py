"""V10: 回测任务模型"""
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from sqlalchemy import Column, BigInteger, String, Date, Boolean, DateTime, DECIMAL, JSON, text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class BacktestTask(Base):
    __tablename__ = "backtest_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbols: Mapped[List[str]] = mapped_column(JSON, nullable=False, comment='["AAPL","NVDA"]')
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_capital: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False, default=100000)
    walk_forward: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", comment="PENDING/RUNNING/DONE/FAILED")
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, comment='{"annualized_return":0.18,"sharpe":1.42,...}')
    error_msg: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_backtest_account_status", "account_id", "status"),
    )
