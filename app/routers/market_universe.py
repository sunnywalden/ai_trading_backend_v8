from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.models.market_universe_symbol import MarketUniverseSymbol
from app.models.strategy import HistoricalStrategyRun, StrategyRun
from app.schemas.market_universe import (
    MarketUniverseMarketStatus,
    MarketUniverseStatusResponse,
)


router = APIRouter(prefix="/market-universe", tags=["Market Universe"])


@router.get("/status", response_model=MarketUniverseStatusResponse, summary="本地全量池状态")
async def get_market_universe_status(session: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=8)
    degraded_reasons: list[str] = []
    markets: list[MarketUniverseMarketStatus] = []

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
        select(func.count(HistoricalStrategyRun.strategy_run_id))
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
    recent_fallback_runs_24h = int((await session.execute(fallback_run_stmt)).scalar() or 0)
    if recent_fallback_runs_24h > 0:
        degraded_reasons.append("RECENT_UNIVERSE_FALLBACK_DETECTED")

    return MarketUniverseStatusResponse(
        degraded=bool(degraded_reasons),
        degraded_reasons=degraded_reasons,
        markets=markets,
        recent_fallback_runs_24h=recent_fallback_runs_24h,
        checked_at=now,
    )
