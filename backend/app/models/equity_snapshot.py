"""V9: 账户权益快照模型"""
from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, DECIMAL, text, Index, UniqueConstraint
from app.models.db import Base


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    total_equity = Column(DECIMAL(20, 2), nullable=False)
    cash = Column(DECIMAL(20, 2), nullable=False, default=0)
    market_value = Column(DECIMAL(20, 2), nullable=False, default=0)
    realized_pnl = Column(DECIMAL(20, 2), nullable=False, default=0)
    unrealized_pnl = Column(DECIMAL(20, 2), nullable=False, default=0)
    daily_return = Column(DECIMAL(10, 6), nullable=True)
    cumulative_return = Column(DECIMAL(10, 6), nullable=True)
    max_drawdown_pct = Column(DECIMAL(10, 6), nullable=True)
    benchmark_return = Column(DECIMAL(10, 6), nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uk_account_date"),
        Index("idx_equity_account_date", "account_id", "snapshot_date"),
    )
