from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, JSON, text, Index
from app.models.db import Base


class TradingPlan(Base):
    __tablename__ = "trading_plan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)

    entry_price = Column(DECIMAL(20, 6), nullable=False)
    stop_loss = Column(DECIMAL(20, 6), nullable=False)
    take_profit = Column(DECIMAL(20, 6), nullable=False)
    target_position = Column(DECIMAL(10, 4), nullable=False)

    plan_status = Column(String(16), nullable=False, default="ACTIVE")
    plan_tags = Column(JSON, nullable=True)

    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    notes = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_plan_account_status", "account_id", "plan_status"),
        Index("idx_plan_symbol", "symbol"),
        Index("idx_plan_valid_until", "valid_until"),
    )
