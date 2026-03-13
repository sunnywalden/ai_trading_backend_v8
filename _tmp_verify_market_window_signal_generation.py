from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from sqlalchemy import select

from app.jobs.strategy_jobs import (
    AUTO_UNIVERSE_KEY,
    _generate_real_assets,
    _maybe_trim_auto_scan_universe,
    _probe_hk_historical_ready_symbols,
    _select_universe_symbols,
)
from app.models.db import SessionLocal
from app.models.strategy import Strategy

STRATEGY_NAME = "量化动量轮动"


async def verify_case(session, local_dt: datetime) -> None:
    strategy = (
        await session.execute(select(Strategy).where(Strategy.name == STRATEGY_NAME))
    ).scalars().first()
    assert strategy is not None, STRATEGY_NAME

    run = SimpleNamespace(
        target_universe=AUTO_UNIVERSE_KEY,
        started_at=local_dt.astimezone(timezone.utc),
        strategy=strategy,
    )
    typed_run = cast(Any, run)
    universe_key, universe_symbols, universe_meta = await _select_universe_symbols(session, typed_run)
    resolved_market = str(universe_meta.get("resolved_market") or "US").upper()
    universe_symbols = _maybe_trim_auto_scan_universe(
        symbols=universe_symbols,
        market=resolved_market,
        task_id="auto_cycle:verify",
    )
    if resolved_market == "HK":
        universe_symbols, hk_probe_meta = await _probe_hk_historical_ready_symbols(
            symbols=universe_symbols,
            task_id="auto_cycle:verify",
        )
        universe_meta = {**universe_meta, **hk_probe_meta}
    sampled, generation_meta = await _generate_real_assets(
        session=session,
        run=typed_run,
        universe_symbols=universe_symbols,
    )
    print({
        "local_time": local_dt.isoformat(),
        "resolved_market": universe_meta.get("resolved_market"),
        "universe_key": universe_key,
        "universe_count": len(universe_symbols),
        "signal_count": len(sampled),
        "sample_symbols": [item.get("symbol") for item in sampled[:5]],
        "sample_directions": [item.get("direction") for item in sampled[:5]],
        "generation_meta": generation_meta,
    })


async def main() -> None:
    async with SessionLocal() as session:
        hk_case = datetime(2026, 3, 13, 14, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
        us_case = datetime(2026, 3, 13, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        await verify_case(session, hk_case)
        await verify_case(session, us_case)


if __name__ == "__main__":
    asyncio.run(main())
