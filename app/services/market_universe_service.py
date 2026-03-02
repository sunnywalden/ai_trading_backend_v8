from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import get_tiger_client
from app.core.cache import cache
from app.models.market_universe_symbol import MarketUniverseSymbol

logger = logging.getLogger(__name__)


class MarketUniverseService:
    """市场全量股票池服务（US/HK）。"""

    _CACHE_PREFIX = "market_universe:"
    _CACHE_TTL_SECONDS = 8 * 24 * 3600  # 8天，覆盖“每周同步一次”窗口

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _normalize_market(market: str) -> str:
        m = (market or "").strip().upper()
        if m not in ("US", "HK"):
            raise ValueError(f"Unsupported market: {market}")
        return m

    async def get_local_universe_symbols(self, market: str) -> List[str]:
        """读取本地 universe（先缓存，后数据库）。"""
        market = self._normalize_market(market)
        cache_key = f"{self._CACHE_PREFIX}{market}"

        try:
            cached = await cache.get(cache_key)
            if isinstance(cached, list) and cached:
                return [str(s).upper() for s in cached if s]
        except Exception as e:
            logger.debug("[MarketUniverse] read cache failed: %s", e)

        stmt = (
            select(MarketUniverseSymbol.symbol)
            .where(
                MarketUniverseSymbol.market == market,
                MarketUniverseSymbol.is_active.is_(True),
            )
            .order_by(MarketUniverseSymbol.symbol.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        symbols = [str(r[0]).upper() for r in rows if r and r[0]]

        if symbols:
            try:
                await cache.set(cache_key, symbols, expire=self._CACHE_TTL_SECONDS)
            except Exception as e:
                logger.debug("[MarketUniverse] write cache failed: %s", e)

        return symbols

    async def refresh_market_universe(self, market: str, include_otc: bool = False) -> Dict[str, int | str]:
        """从 Tiger 拉取某市场全量 symbol，并落库/刷新缓存。"""
        market = self._normalize_market(market)
        tiger = get_tiger_client()
        if not tiger:
            raise RuntimeError("Tiger client is not configured")

        try:
            from tigeropen.common.consts import Market as TigerMarket
        except Exception as e:
            raise RuntimeError(f"Tiger SDK import failed: {e}") from e

        market_enum = TigerMarket.US if market == "US" else TigerMarket.HK

        # get_symbol_names -> list[tuple[symbol, name]]
        rows = await asyncio.to_thread(
            tiger.quote_client.get_symbol_names,
            market_enum,
            None,
            include_otc,
        )

        fetched: Dict[str, str | None] = {}
        for item in rows or []:
            if not item:
                continue
            symbol = str(item[0]).strip().upper()
            if not symbol:
                continue
            name = str(item[1]).strip() if len(item) > 1 and item[1] else None
            fetched[symbol] = name

        now = datetime.now(timezone.utc)

        existing_stmt = select(MarketUniverseSymbol).where(MarketUniverseSymbol.market == market)
        existing_rows = (await self.session.execute(existing_stmt)).scalars().all()
        existing_map = {str(r.symbol).upper(): r for r in existing_rows}

        inserted = 0
        updated = 0

        for symbol, name in fetched.items():
            row = existing_map.get(symbol)
            if row is None:
                self.session.add(
                    MarketUniverseSymbol(
                        symbol=symbol,
                        market=market,
                        name=name,
                        source="tiger",
                        is_active=True,
                        last_synced_at=now,
                    )
                )
                inserted += 1
            else:
                row.name = name
                row.source = "tiger"
                row.is_active = True
                row.last_synced_at = now
                updated += 1

        deactivated = 0
        fetched_set = set(fetched.keys())
        for symbol, row in existing_map.items():
            if symbol not in fetched_set and row.is_active:
                row.is_active = False
                row.last_synced_at = now
                deactivated += 1

        await self.session.commit()

        # 写入本地缓存
        cache_key = f"{self._CACHE_PREFIX}{market}"
        symbols = sorted(fetched.keys())
        try:
            await cache.set(cache_key, symbols, expire=self._CACHE_TTL_SECONDS)
        except Exception as e:
            logger.debug("[MarketUniverse] write cache failed: %s", e)

        return {
            "market": market,
            "fetched": len(fetched),
            "inserted": inserted,
            "updated": updated,
            "deactivated": deactivated,
        }

    async def refresh_all_markets(self) -> Dict[str, Dict[str, int | str]]:
        us = await self.refresh_market_universe("US")
        hk = await self.refresh_market_universe("HK")
        return {"US": us, "HK": hk}
