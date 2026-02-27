import asyncio
from app.models.db import engine
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

asyncio.run(check_data())
