"""V10: 模拟账户（Paper Trading）模型"""
from sqlalchemy import Column, BigInteger, String, DateTime, DECIMAL, JSON, text
from app.models.db import Base


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, unique=True)
    initial_capital = Column(DECIMAL(20, 2), nullable=False, default=100000)
    current_equity = Column(DECIMAL(20, 2), nullable=False)
    realized_pnl = Column(DECIMAL(20, 2), default=0)
    unrealized_pnl = Column(DECIMAL(20, 2), default=0)
    positions = Column(JSON, nullable=True, comment="当前模拟持仓")
    trade_log = Column(JSON, nullable=True, comment="历史成交记录（最近500条）")
    reset_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))
