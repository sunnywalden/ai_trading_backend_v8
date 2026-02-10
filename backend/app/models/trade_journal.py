"""V9: 交易日志/复盘模型"""
from sqlalchemy import Column, BigInteger, Integer, String, Date, DateTime, DECIMAL, JSON, Text, text, Index
from app.models.db import Base


class TradeJournal(Base):
    __tablename__ = "trade_journal"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    direction = Column(String(8), nullable=False)
    entry_date = Column(Date, nullable=True)
    exit_date = Column(Date, nullable=True)
    entry_price = Column(DECIMAL(20, 6), nullable=True)
    exit_price = Column(DECIMAL(20, 6), nullable=True)
    quantity = Column(DECIMAL(20, 6), nullable=True)
    realized_pnl = Column(DECIMAL(20, 2), nullable=True)
    plan_id = Column(Integer, nullable=True)
    execution_quality = Column(Integer, nullable=True)
    emotion_state = Column(String(16), nullable=True)
    mistake_tags = Column(JSON, nullable=True)
    lesson_learned = Column(Text, nullable=True)
    ai_review = Column(Text, nullable=True)
    journal_status = Column(String(16), nullable=False, default="DRAFT")
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_journal_account_date", "account_id", "entry_date"),
        Index("idx_journal_symbol", "symbol"),
    )
