"""V10: TWAP/VWAP 算法执行任务模型"""
from sqlalchemy import Column, BigInteger, String, DateTime, DECIMAL, Integer, JSON, text, Index
from app.models.db import Base


class AlgoExecutionTask(Base):
    __tablename__ = "algo_execution_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    side = Column(String(4), nullable=False, comment="BUY/SELL")
    algo = Column(String(8), nullable=False, comment="TWAP/VWAP/MKT")
    total_qty = Column(DECIMAL(20, 6), nullable=False)
    filled_qty = Column(DECIMAL(20, 6), default=0)
    avg_price = Column(DECIMAL(20, 6), default=0)
    slices = Column(Integer, default=10)
    interval_secs = Column(Integer, default=60)
    status = Column(String(16), default="PENDING", comment="PENDING/RUNNING/DONE/CANCELLED")
    slices_log = Column(JSON, nullable=True, comment="每片执行记录")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_algo_account_status", "account_id", "status"),
    )
