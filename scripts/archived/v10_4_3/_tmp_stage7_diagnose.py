from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import json

from sqlalchemy import text

from app.models.db import SessionLocal


SQL = text(
    """
    WITH stage7 AS (
        SELECT
            p.id,
            p.symbol,
            p.account_id,
            p.pipeline_stage,
            p.plan_status,
            p.position_fsm_state,
            p.stage_entered_at,
            p.updated_at,
            p.created_at,
            TIMESTAMPDIFF(SECOND, p.stage_entered_at, UTC_TIMESTAMP()) AS stayed_seconds
        FROM trading_plan p
        WHERE p.pipeline_stage = 7
        ORDER BY p.stage_entered_at ASC
        LIMIT 80
    ),
    latest_signal AS (
        SELECT
            s.symbol,
            s.account_id,
            s.id AS signal_id,
            s.status AS signal_status,
            s.order_id,
            s.created_at AS signal_created_at,
            ROW_NUMBER() OVER (PARTITION BY s.account_id, s.symbol ORDER BY s.created_at DESC, s.id DESC) AS rn
        FROM trading_signals s
        WHERE s.account_id IS NOT NULL
    )
    SELECT
        g.*,
        ls.signal_id,
        ls.signal_status,
        ls.order_id,
        ls.signal_created_at
    FROM stage7 g
    LEFT JOIN latest_signal ls
      ON ls.account_id = g.account_id
     AND ls.symbol = g.symbol
     AND ls.rn = 1
    ORDER BY g.stage_entered_at ASC, g.id ASC
    """
)

COUNT_SQL = text(
    """
    SELECT pipeline_stage, plan_status, position_fsm_state, COUNT(*) AS cnt
    FROM trading_plan
    WHERE pipeline_stage = 7
    GROUP BY pipeline_stage, plan_status, position_fsm_state
    ORDER BY cnt DESC, plan_status, position_fsm_state
    """
)


async def main() -> None:
    async with SessionLocal() as db:
        counts = [dict(row._mapping) for row in (await db.execute(COUNT_SQL)).fetchall()]
        rows = [dict(row._mapping) for row in (await db.execute(SQL)).fetchall()]
    print(json.dumps({"counts": counts, "rows": rows}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
