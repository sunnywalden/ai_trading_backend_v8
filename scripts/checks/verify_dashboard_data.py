from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
from app.models.db import engine, close_db_resources
from sqlalchemy import text
from datetime import date, timedelta

async def check_data():
    async with engine.connect() as conn:
        print("--- Equity Snapshots ---")
        res = await conn.execute(text("SELECT snapshot_date, total_equity FROM equity_snapshots ORDER BY snapshot_date DESC LIMIT 15"))
        for r in res:
            print(f"Date: {r[0]}, Equity: {r[1]}")
            
        print("\n--- Strategy Runs ---")
        res = await conn.execute(text("SELECT status, count(*) FROM strategy_runs GROUP BY status"))
        for r in res:
            print(f"Status: {r[0]}, Count: {r[1]}")


async def main():
    try:
        await check_data()
    finally:
        await close_db_resources()


if __name__ == "__main__":
    asyncio.run(main())
