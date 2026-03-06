from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import json
from sqlalchemy import text
from app.models.db import SessionLocal

SQL = text("""
SELECT fsm_type, COUNT(*) AS cnt
FROM fsm_transition_log
GROUP BY fsm_type
ORDER BY cnt DESC
""")

SAMPLE_SQL = text("""
SELECT id, plan_id, fsm_type, from_state, to_state, engine, trigger_reason, occurred_at
FROM fsm_transition_log
WHERE fsm_type = :fsm_type
ORDER BY occurred_at DESC, id DESC
LIMIT 10
""")

async def main() -> None:
    async with SessionLocal() as db:
        counts = [dict(row._mapping) for row in (await db.execute(SQL)).fetchall()]
        samples = {}
        for item in counts:
            fsm_type = item['fsm_type']
            samples[fsm_type] = [dict(row._mapping) for row in (await db.execute(SAMPLE_SQL, {'fsm_type': fsm_type})).fetchall()]
    print(json.dumps({'counts': counts, 'samples': samples}, ensure_ascii=False, indent=2, default=str))

if __name__ == '__main__':
    asyncio.run(main())
