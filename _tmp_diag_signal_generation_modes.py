from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from app.jobs.strategy_jobs import _resolve_market_by_runtime
from app.models.db import SessionLocal

ACCOUNT_ID = "21272246230273657"


async def main() -> None:
    async with SessionLocal() as s:
        q = text(
            """
            SELECT sr.id,
                   sr.finished_at,
                   st.name AS strategy_name,
                   h.hits,
                   h.scanned_total,
                   JSON_EXTRACT(h.status_payload, '$.signal_generation.resolved_strategy_key') AS resolved_strategy_key,
                   JSON_EXTRACT(h.status_payload, '$.signal_generation.fallback_reason') AS fallback_reason,
                   JSON_EXTRACT(h.status_payload, '$.universe.resolved_market') AS resolved_market,
                   JSON_EXTRACT(h.status_payload, '$.universe.symbols_count') AS symbols_count,
                   JSON_EXTRACT(h.status_payload, '$.signal_generation.raw_signal_count') AS raw_signal_count
            FROM strategy_runs sr
            LEFT JOIN strategies st ON st.id = sr.strategy_id
            LEFT JOIN historical_strategy_runs h ON h.strategy_run_id = sr.id
            WHERE sr.account_id = :account_id
              AND sr.celery_task_id LIKE 'auto_cycle:%'
            ORDER BY sr.finished_at DESC
            LIMIT 9
            """
        )
        rows = (await s.execute(q, {"account_id": ACCOUNT_ID})).mappings().all()
        print("LATEST AUTO CYCLE RUNS:")
        for row in rows:
            print(dict(row))

    hk_runtime = datetime(2026, 3, 13, 14, 8, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    us_runtime = datetime(2026, 3, 13, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    print("\nRUNTIME MARKET RESOLUTION:")
    print({"hk_case_runtime_utc": hk_runtime.isoformat(), "market": _resolve_market_by_runtime(hk_runtime)})
    print({"us_case_runtime_utc": us_runtime.isoformat(), "market": _resolve_market_by_runtime(us_runtime)})


if __name__ == "__main__":
    asyncio.run(main())
