"""V9: 交易盈亏归因模型"""
from sqlalchemy import Column, BigInteger, Integer, String, Date, DateTime, DECIMAL, text, Index
from app.models.db import Base


class TradePnlAttribution(Base):
    __tablename__ = "trade_pnl_attribution"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    trade_date = Column(Date, nullable=False)
    direction = Column(String(8), nullable=False)
    entry_price = Column(DECIMAL(20, 6), nullable=False)
    exit_price = Column(DECIMAL(20, 6), nullable=True)
    quantity = Column(DECIMAL(20, 6), nullable=False)
    realized_pnl = Column(DECIMAL(20, 2), nullable=True)
    holding_days = Column(Integer, nullable=True)
    strategy_tag = Column(String(64), nullable=True)
    factor_tag = Column(String(64), nullable=True)
    plan_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_pnl_account_date", "account_id", "trade_date"),
        Index("idx_pnl_symbol", "symbol"),
    )
