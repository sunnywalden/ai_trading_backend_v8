from __future__ import annotations

import asyncio
import json

from sqlalchemy import bindparam, text

from app.models.db import SessionLocal

RUN_IDS = [
    "f2b17f96-5553-4381-9166-bc82e71fc0c1",
    "2a7892ae-ef0f-4545-8ee3-27e990ea0abe",
    "f9dcbee6-9015-42c3-8b1d-689b7001b70e",
    "9a3f2062-1a1f-4268-8642-c4b03504a060",
    "0b751b72-c1d5-4a02-b716-082d64adf7e2",
    "0c4de7a2-c0eb-411d-8263-2060d47d72b9",
    "7ac53a6f-7a9b-4835-bf86-2dfd73471ab5",
]


async def main() -> None:
    async with SessionLocal() as s:
        q = text(
            """
            SELECT sr.id,
                   st.name AS strategy_name,
                   sr.started_at,
                   h.hits,
                   h.scanned_total,
                   h.status_payload
            FROM strategy_runs sr
            LEFT JOIN strategies st ON st.id = sr.strategy_id
            LEFT JOIN historical_strategy_runs h ON h.strategy_run_id = sr.id
            WHERE sr.id IN :run_ids
            ORDER BY sr.started_at ASC
            """
        ).bindparams(bindparam("run_ids", expanding=True))
        rows = (await s.execute(q, {"run_ids": RUN_IDS})).mappings().all()
        for row in rows:
            payload = row["status_payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    pass
            print("RUN", row["id"], row["strategy_name"], row["started_at"], row["hits"], row["scanned_total"])
            print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
            print("-" * 80)


if __name__ == "__main__":
    asyncio.run(main())
