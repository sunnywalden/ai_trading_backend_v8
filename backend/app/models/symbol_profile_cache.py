"""股票基础信息缓存（市值/行业）

用途：支持“按市值/行业动态筛选股票池”，在 yfinance 限流时仍可依赖历史缓存。

注意：这不是“机会结果”的落库结构；机会结果仍是 run + items 两张表。
"""

from sqlalchemy import Column, Integer, String, DateTime, BigInteger, UniqueConstraint, Index
from sqlalchemy.sql import func

from app.models.db import Base


class SymbolProfileCache(Base):
    __tablename__ = "symbol_profile_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)

    symbol = Column(String, nullable=False)
    market_cap = Column(BigInteger)
    sector = Column(String)
    industry = Column(String)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", name="uq_symbol_profile_cache_symbol"),
        Index("ix_symbol_profile_cache_symbol", "symbol"),
        Index("ix_symbol_profile_cache_updated_at", "updated_at"),
    )
