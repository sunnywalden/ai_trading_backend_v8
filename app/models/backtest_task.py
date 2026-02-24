"""V10: 回测任务模型"""
from sqlalchemy import Column, BigInteger, String, Date, Boolean, DateTime, DECIMAL, JSON, text, Index
from app.models.db import Base


class BacktestTask(Base):
    __tablename__ = "backtest_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    strategy_name = Column(String(128), nullable=False)
    symbols = Column(JSON, nullable=False, comment='["AAPL","NVDA"]')
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_capital = Column(DECIMAL(20, 2), nullable=False, default=100000)
    walk_forward = Column(Boolean, default=False)
    status = Column(String(16), default="PENDING", comment="PENDING/RUNNING/DONE/FAILED")
    result = Column(JSON, nullable=True, comment='{"annualized_return":0.18,"sharpe":1.42,...}')
    error_msg = Column(String(2048), nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_backtest_account_status", "account_id", "status"),
    )
