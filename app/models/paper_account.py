from datetime import datetime
from typing import Optional, Dict, List, Any
from sqlalchemy import Column, BigInteger, String, DateTime, DECIMAL, JSON, text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    initial_capital: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False, default=100000)
    current_equity: Mapped[float] = mapped_column(DECIMAL(20, 2), nullable=False)
    realized_pnl: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 2), default=0)
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 2), default=0)
    positions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, comment="当前模拟持仓")
    trade_log: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True, comment="历史成交记录（最近500条）")
    reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))
