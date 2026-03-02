from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class MarketUniverseSymbol(Base):
    """本地市场全量股票池（US/HK）。

    用于机会扫描快速读取本地 universe，避免实时依赖远端接口。
    """

    __tablename__ = "market_universe_symbols"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)  # US / HK
    name: Mapped[Optional[str]] = mapped_column(String(256))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tiger")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("market", "symbol", name="uq_market_universe_symbol"),
        Index("ix_market_universe_market_active", "market", "is_active"),
        Index("ix_market_universe_symbol", "symbol"),
    )
