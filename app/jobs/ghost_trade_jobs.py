"""V10.4.2: ghost_trade_jobs.py — 幽灵交易每日追踪任务

定时任务（美东时间 16:35，盘后）：
  - 获取当日所有仍处于 OPEN 状态的幽灵交易标的收盘价
  - 更新 PnL、价格历史，判断 WIN/LOSS/EXPIRED
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.ghost_trade import GhostTrade, GhostTradeResult
from app.services.ghost_trade_service import ghost_trade_service

logger = logging.getLogger(__name__)


async def update_ghost_trades_pnl() -> None:
    """
    每日收盘后（16:35 ET）批量更新幽灵交易 PnL。

    流程：
    1. 查询所有 OPEN 状态的幽灵交易，收集 symbol 列表
    2. 批量从行情接口获取最新收盘价
    3. 调用 ghost_trade_service.update_daily_prices()
    """
    async with SessionLocal() as db:
        try:
            # Step 1: 查询 OPEN 交易
            stmt = select(GhostTrade.symbol).where(
                GhostTrade.ghost_result == GhostTradeResult.OPEN
            )
            rows = (await db.execute(stmt)).all()
            symbols = list({r[0] for r in rows if r[0]})

            if not symbols:
                logger.info("[GhostTradeJob] No open ghost trades, skip update")
                return

            logger.info(f"[GhostTradeJob] Updating {len(symbols)} symbols: {symbols[:10]}...")

            # Step 2: 批量获取收盘价
            price_map: dict[str, float] = await _fetch_close_prices(symbols)

            if not price_map:
                logger.warning("[GhostTradeJob] Could not fetch any prices, skip update")
                return

            # Step 3: 更新 PnL
            updated = await ghost_trade_service.update_daily_prices(db, price_map)
            await db.commit()
            logger.info(f"[GhostTradeJob] Updated {updated} ghost trade records")

        except Exception as e:
            logger.error(f"[GhostTradeJob] Failed to update ghost trades: {e}")
            try:
                await db.rollback()
            except Exception:
                pass


async def _fetch_close_prices(symbols: list[str]) -> dict[str, float]:
    """
    从已有行情接口批量获取标的最新价格。

    优先使用 Tiger Broker 行情；若全部失败则返回空 dict（不阻断流程）。
    """
    price_map: dict[str, float] = {}

    # ── 方案 A: Tiger 行情 ──────────────────────────────────────────────────
    try:
        from app.broker.factory import make_option_broker_client
        broker = make_option_broker_client()
        for sym in symbols:
            try:
                quote = await broker.get_stock_quote(sym)
                p = _extract_price_from_quote(quote)
                if p and p > 0:
                    price_map[sym] = p
            except Exception as _e:
                logger.debug(f"[GhostTradeJob] broker quote failed for {sym}: {_e}")
    except Exception as e:
        logger.warning(f"[GhostTradeJob] Tiger broker batch quote failed: {e}")

    if price_map:
        return price_map

    # ── 方案 B: Redis 缓存价格（quant_loop 更新的实时快照）─────────────────
    try:
        from app.models.db import get_redis
        redis = await get_redis()
        if redis is None:
            return price_map
        for sym in symbols:
            key = f"price:latest:{sym}"
            val = await redis.get(key)
            if val:
                price_map[sym] = float(val)
    except Exception as e:
        logger.warning(f"[GhostTradeJob] Redis price fallback failed: {e}")

    return price_map


def _extract_price_from_quote(quote) -> Optional[float]:
    """从 broker quote 对象提取价格（兼容 dict / dataclass）。"""
    if quote is None:
        return None
    if isinstance(quote, dict):
        for k in ("close", "last_price", "last", "price"):
            v = quote.get(k)
            if v is not None and float(v) > 0:
                return float(v)
    else:
        for attr in ("close", "last_price", "last", "price"):
            v = getattr(quote, attr, None)
            if v is not None and float(v) > 0:
                return float(v)
    return None
