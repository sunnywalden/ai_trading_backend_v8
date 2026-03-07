from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.models.market_universe_symbol import MarketUniverseSymbol
from app.models.strategy import HistoricalStrategyRun, StrategyRun
from app.schemas.market_universe import (MarketUniverseMarketStatus,
                                         MarketUniverseStatusResponse)

router = APIRouter(prefix="/market-universe", tags=["Market Universe"])


def _normalize_market(value: Any) -> str | None:
    if value is None:
        return None
    market = str(value).strip().upper()
    return market if market in {"US", "HK"} else None


def _is_truthy_json_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes"}


@router.get("/status", response_model=MarketUniverseStatusResponse, summary="本地全量池状态")
async def get_market_universe_status(session: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=8)
    degraded_reasons: list[str] = []
    markets: list[MarketUniverseMarketStatus] = []
    market_sync_map: dict[str, datetime | None] = {}

    for market in ("US", "HK"):
        active_count_stmt = (
            select(func.count(MarketUniverseSymbol.id))
            .where(
                and_(
                    MarketUniverseSymbol.market == market,
                    MarketUniverseSymbol.is_active.is_(True),
                )
            )
        )
        active_count = int((await session.execute(active_count_stmt)).scalar() or 0)

        last_sync_stmt = (
            select(func.max(MarketUniverseSymbol.last_synced_at))
            .where(MarketUniverseSymbol.market == market)
        )
        last_synced_at = (await session.execute(last_sync_stmt)).scalar()
        if last_synced_at and last_synced_at.tzinfo is None:
            last_synced_at = last_synced_at.replace(tzinfo=timezone.utc)
        market_sync_map[market] = last_synced_at

        stale = bool(not last_synced_at or last_synced_at < stale_threshold)

        if active_count <= 0:
            degraded_reasons.append(f"{market}_POOL_EMPTY")
        if stale:
            degraded_reasons.append(f"{market}_POOL_STALE")

        markets.append(
            MarketUniverseMarketStatus(
                market=market,
                active_symbols=active_count,
                last_synced_at=last_synced_at,
                stale=stale,
            )
        )

    # 最近24小时是否出现过“降级到默认样本池”的策略运行
    since = now - timedelta(hours=24)
    fallback_run_stmt = (
        select(
            StrategyRun.created_at,
            func.json_unquote(
                func.json_extract(
                    HistoricalStrategyRun.status_payload,
                    "$.universe.resolved_market",
                )
            ).label("resolved_market"),
            func.json_extract(
                HistoricalStrategyRun.status_payload,
                "$.universe.fallback_to_default_symbols",
            ).label("fallback_to_default_symbols"),
            func.json_unquote(
                func.json_extract(
                    HistoricalStrategyRun.status_payload,
                    "$.universe.fallback_reason",
                )
            ).label("fallback_reason"),
        )
        .select_from(HistoricalStrategyRun)
        .join(StrategyRun, StrategyRun.id == HistoricalStrategyRun.strategy_run_id)
        .where(
            and_(
                StrategyRun.created_at >= since,
                or_(
                    func.json_extract(
                        HistoricalStrategyRun.status_payload,
                        "$.universe.fallback_to_default_symbols",
                    )
                    == 1,
                    func.json_extract(
                        HistoricalStrategyRun.status_payload,
                        "$.universe.fallback_reason",
                    )
                    .is_not(None),
                ),
            )
        )
    )
    fallback_rows = (await session.execute(fallback_run_stmt)).all()
    recent_fallback_runs_24h = 0

    for row in fallback_rows:
        run_created_at = row.created_at
        if run_created_at and run_created_at.tzinfo is None:
            run_created_at = run_created_at.replace(tzinfo=timezone.utc)

        resolved_market = _normalize_market(row.resolved_market)
        fallback_reason = row.fallback_reason
        fallback_flag = _is_truthy_json_flag(row.fallback_to_default_symbols)

        if not fallback_flag and not fallback_reason:
            continue

        if resolved_market is None and isinstance(fallback_reason, str):
            if fallback_reason.startswith("HK_"):
                resolved_market = "HK"
            elif fallback_reason.startswith("US_"):
                resolved_market = "US"

        latest_sync = market_sync_map.get(resolved_market) if resolved_market else None

        # 仅在最近一次池同步之后仍发生回退时，才视为当前降级。
        if latest_sync and run_created_at and run_created_at <= latest_sync:
            continue

        recent_fallback_runs_24h += 1

    if recent_fallback_runs_24h > 0:
        degraded_reasons.append("RECENT_UNIVERSE_FALLBACK_DETECTED")

    return MarketUniverseStatusResponse(
        degraded=bool(degraded_reasons),
        degraded_reasons=degraded_reasons,
        markets=markets,
        recent_fallback_runs_24h=recent_fallback_runs_24h,
        checked_at=now,
    )
