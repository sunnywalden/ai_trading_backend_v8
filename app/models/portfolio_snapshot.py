"""V10: 投资组合优化快照模型"""
from sqlalchemy import Column, BigInteger, String, DateTime, DECIMAL, JSON, text, Index
from app.models.db import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    method = Column(String(32), nullable=False, comment="MARKOWITZ/RISK_PARITY/KELLY")
    current_weights = Column(JSON, nullable=False, comment='{"AAPL":0.22,"NVDA":0.12}')
    target_weights = Column(JSON, nullable=False, comment='{"AAPL":0.15,"NVDA":0.20}')
    frontier_data = Column(JSON, nullable=True, comment="有效前沿散点数据")
    expected_return = Column(DECIMAL(10, 6), nullable=True)
    expected_volatility = Column(DECIMAL(10, 6), nullable=True)
    sharpe_ratio = Column(DECIMAL(10, 4), nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_portfolio_account_time", "account_id", "created_at"),
    )
