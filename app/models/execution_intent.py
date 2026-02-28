from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class AutonomousExecutionIntent(Base):
    """自主执行意图（幂等主键）。

    用于防止同一信号在并发/重复触发场景下被重复执行。
    """

    __tablename__ = "autonomous_execution_intent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intent_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signal_db_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_exec_intent_account_symbol", "account_id", "symbol"),
        Index("idx_exec_intent_status", "status"),
    )
