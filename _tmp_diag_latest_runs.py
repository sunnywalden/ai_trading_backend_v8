import asyncio
from sqlalchemy import text
from app.models.db import SessionLocal

async def main() -> None:
    async with SessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT sr.id, sr.created_at, st.name AS strategy_name,
                   h.hits, h.scanned_total, h.status_payload
            FROM strategy_runs sr
            LEFT JOIN strategies st ON st.id = sr.strategy_id
            LEFT JOIN historical_strategy_runs h ON h.strategy_run_id = sr.id
            ORDER BY sr.created_at DESC
            LIMIT 5
        """))).mappings().all()
        for row in rows:
            print("RUN", row["id"], row["strategy_name"], row["created_at"], "hits=", row["hits"], "scanned=", row["scanned_total"])
            print(row["status_payload"])
            print("-" * 80)

if __name__ == "__main__":
    asyncio.run(main())
