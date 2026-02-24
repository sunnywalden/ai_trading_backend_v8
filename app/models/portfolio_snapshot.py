"""V10: 投资组合优化快照模型"""
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import Column, BigInteger, String, DateTime, DECIMAL, JSON, text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, comment="MARKOWITZ/RISK_PARITY/KELLY")
    current_weights: Mapped[Dict[str, float]] = mapped_column(JSON, nullable=False, comment='{"AAPL":0.22,"NVDA":0.12}')
    target_weights: Mapped[Dict[str, float]] = mapped_column(JSON, nullable=False, comment='{"AAPL":0.15,"NVDA":0.20}')
    frontier_data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="有效前沿散点数据")
    expected_return: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    expected_volatility: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 6), nullable=True)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(DECIMAL(10, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_portfolio_account_time", "account_id", "created_at"),
    )
