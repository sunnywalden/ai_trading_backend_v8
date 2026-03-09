"""quote_freshness_service.py — 行情 freshness 自愈服务。

目标：
1. 为 Live Safety / Autonomy Health 提供统一的 quote 最新时间来源。
2. 当 technical_indicators 表陈旧时，按需拉取少量代表性标的行情并刷新技术指标缓存。
3. 通过 Redis heartbeat 避免前端轮询时重复触发外部行情请求。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.config import settings
from app.models.position import Position, PositionStatus
from app.models.technical_indicator import TechnicalIndicator
from app.models.trading_plan import TradingPlan
from app.providers.market_data_provider import market_data_provider
from app.services.freshness_heartbeat import (max_available_timestamp,
                                              normalize_timestamp,
                                              read_heartbeat_timestamp,
                                              write_heartbeat_timestamp)
from app.services.technical_analysis_service import TechnicalAnalysisService

logger = logging.getLogger(__name__)

_QUOTE_FRESHNESS_HEARTBEAT_KEY = "live_safety:quote_freshness:last_seen"
_SELF_HEAL_STALE_MINUTES = 90.0
_DEFAULT_SYMBOLS = ["SPY"]
_ACTIVE_POSITION_STATUSES = [
    PositionStatus.PENDING.value,
    PositionStatus.OPENING.value,
    PositionStatus.ACTIVE.value,
    PositionStatus.SCALING_IN.value,
    PositionStatus.SCALING_OUT.value,
    PositionStatus.CLOSING.value,
    PositionStatus.PARTIALLY_CLOSED.value,
    PositionStatus.EXCEPTION.value,
]


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_heartbeat_timestamp() -> datetime | None:
    try:
        return await read_heartbeat_timestamp(_QUOTE_FRESHNESS_HEARTBEAT_KEY)
    except Exception as exc:
        logger.debug("[QuoteFreshness] heartbeat read failed: %s", exc)
        return None


async def _set_heartbeat_timestamp(ts: datetime) -> None:
    try:
        await write_heartbeat_timestamp(
            _QUOTE_FRESHNESS_HEARTBEAT_KEY,
            ts,
            ttl_seconds=60 * 60,
        )
    except Exception as exc:
        logger.debug("[QuoteFreshness] heartbeat write failed: %s", exc)


async def _latest_indicator_timestamp(db: AsyncSession) -> datetime | None:
    stmt = (
        select(TechnicalIndicator.timestamp)
        .order_by(desc(TechnicalIndicator.timestamp))
        .limit(1)
    )
    result = await db.execute(stmt)
    return normalize_timestamp(result.scalar_one_or_none())


def _candidate_account_keys(account_id: str | None) -> list[str]:
    raw_values = [account_id, settings.TIGER_ACCOUNT]
    keys: list[str] = []
    for raw in raw_values:
        if not raw:
            continue
        value = str(raw)
        for candidate in [value, value.split("@", 1)[0], value[5:] if value.lower().startswith("user_") else value]:
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


def _extract_symbol(item: Any) -> str | None:
    if item is None:
        return None
    if isinstance(item, dict):
        symbol = item.get("symbol")
    else:
        symbol = getattr(item, "symbol", None)
    if symbol is None:
        return None
    text = str(symbol).strip().upper()
    return text or None


async def _collect_quote_symbols(
    db: AsyncSession,
    account_id: str | None,
    max_symbols: int,
) -> list[str]:
    symbols: list[str] = []
    keys = _candidate_account_keys(account_id)

    def add_symbol(symbol: str | None) -> None:
        if symbol and symbol not in symbols:
            symbols.append(symbol)

    broker_account_id = str(account_id or settings.TIGER_ACCOUNT)
    try:
        broker = make_option_broker_client()
        resolved_account_id = await broker.get_account_id()
        if resolved_account_id:
            broker_account_id = str(resolved_account_id)
            if broker_account_id not in keys:
                keys.insert(0, broker_account_id)
        positions = await broker.list_underlying_positions(broker_account_id)
        for position in positions or []:
            add_symbol(_extract_symbol(position))
            if len(symbols) >= max_symbols:
                return symbols[:max_symbols]
    except Exception as exc:
        logger.debug("[QuoteFreshness] broker symbol collection failed: %s", exc)

    try:
        pos_stmt = (
            select(Position.symbol)
            .where(
                Position.account_id.in_(keys),
                Position.status.in_(_ACTIVE_POSITION_STATUSES),
            )
            .order_by(desc(Position.updated_at))
            .limit(max_symbols)
        )
        for symbol in (await db.execute(pos_stmt)).scalars().all():
            add_symbol(str(symbol).upper())
            if len(symbols) >= max_symbols:
                return symbols[:max_symbols]
    except Exception as exc:
        logger.debug("[QuoteFreshness] position symbol collection failed: %s", exc)

    try:
        any_pos_stmt = (
            select(Position.symbol)
            .where(Position.status.in_(_ACTIVE_POSITION_STATUSES))
            .order_by(desc(Position.updated_at))
            .limit(max_symbols)
        )
        for symbol in (await db.execute(any_pos_stmt)).scalars().all():
            add_symbol(str(symbol).upper())
            if len(symbols) >= max_symbols:
                return symbols[:max_symbols]
    except Exception as exc:
        logger.debug("[QuoteFreshness] global position symbol collection failed: %s", exc)

    try:
        plan_stmt = (
            select(TradingPlan.symbol)
            .where(
                TradingPlan.account_id.in_(keys),
                TradingPlan.plan_status.in_(["ACTIVE", "PARTIAL"]),
            )
            .order_by(desc(TradingPlan.updated_at))
            .limit(max_symbols)
        )
        for symbol in (await db.execute(plan_stmt)).scalars().all():
            add_symbol(str(symbol).upper())
            if len(symbols) >= max_symbols:
                return symbols[:max_symbols]
    except Exception as exc:
        logger.debug("[QuoteFreshness] trading plan symbol collection failed: %s", exc)

    if not symbols:
        symbols.extend(_DEFAULT_SYMBOLS)

    return symbols[:max_symbols]


async def refresh_quote_freshness(
    db: AsyncSession,
    account_id: str | None = None,
    *,
    max_symbols: int = 4,
) -> dict[str, Any]:
    """主动刷新少量代表性标的的技术指标时间戳，修复 quote freshness。"""
    symbols = await _collect_quote_symbols(db, account_id, max_symbols=max_symbols)
    effective_account_id = str(account_id or settings.TIGER_ACCOUNT or "SYSTEM")
    technical_service = TechnicalAnalysisService(db)

    refreshed_symbols: list[str] = []
    failures: dict[str, str] = {}
    latest_seen: datetime | None = None

    for symbol in symbols:
        try:
            df = await market_data_provider.get_historical_data(
                symbol,
                period="6mo",
                interval="1d",
            )
            if df is None or getattr(df, "empty", True):
                failures[symbol] = "no historical data"
                continue

            await technical_service.get_technical_analysis(
                symbol,
                timeframe="1D",
                use_cache=False,
                account_id=effective_account_id,
                pre_fetched_df=df,
                use_ai=False,
            )
            refreshed_symbols.append(symbol)
            latest_seen = _utc_now_naive()
        except Exception as exc:
            failures[symbol] = str(exc)[:160]
            logger.debug("[QuoteFreshness] refresh failed for %s: %s", symbol, exc)

    if latest_seen is not None:
        await _set_heartbeat_timestamp(latest_seen)

    return {
        "account_id": effective_account_id,
        "symbols_attempted": symbols,
        "refreshed_symbols": refreshed_symbols,
        "success_count": len(refreshed_symbols),
        "failure_count": len(failures),
        "failures": failures,
        "latest_seen": latest_seen.isoformat() if latest_seen else None,
    }


async def get_latest_quote_timestamp(
    db: AsyncSession,
    account_id: str | None = None,
    *,
    allow_self_heal: bool = False,
    max_symbols: int = 4,
) -> datetime | None:
    """统一返回 quote freshness 时间戳；必要时做一次自愈刷新。"""
    latest_db = await _latest_indicator_timestamp(db)
    latest_heartbeat = await _get_heartbeat_timestamp()
    latest = max_available_timestamp(latest_db, latest_heartbeat)

    if not allow_self_heal:
        return latest

    now = _utc_now_naive()
    age_minutes = (
        (now - latest).total_seconds() / 60.0 if latest is not None else float("inf")
    )
    if age_minutes < _SELF_HEAL_STALE_MINUTES:
        return latest

    refresh_result = await refresh_quote_freshness(
        db,
        account_id=account_id,
        max_symbols=max_symbols,
    )
    latest_seen = refresh_result.get("latest_seen")
    if latest_seen:
        return normalize_timestamp(datetime.fromisoformat(str(latest_seen)))
    return latest
