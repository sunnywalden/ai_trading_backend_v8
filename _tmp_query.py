import asyncio
import sys
import os

sys.path.insert(0, '.')
os.environ.setdefault('ENV', 'production')

from sqlalchemy import text
from app.models.db import SessionLocal


async def query():
    async with SessionLocal() as session:
        # Active non-HK trading_plan records
        # First check columns
        col_result = await session.execute(text("DESCRIBE trading_plan"))
        cols = col_result.fetchall()
        print("=== trading_plan columns ===")
        for c in cols:
            print(f"  {c[0]} ({c[1]})")
        
        # BUY intents per symbol (non-HK), grouped by symbol
        result = await session.execute(text(
            "SELECT symbol, action, status, SUM(qty) as total_qty, "
            "MIN(created_at) as first_at, COUNT(*) as cnt "
            "FROM autonomous_execution_intent "
            "WHERE symbol NOT REGEXP '^[0-9]{5}$' "
            "GROUP BY symbol, action, status "
            "ORDER BY symbol, action"
        ))
        rows = result.fetchall()
        print(f"\n=== BUY/SELL intents by symbol (non-HK) ===")
        for r in rows:
            print(f"  symbol={r[0]} action={r[1]} status={r[2]} total_qty={r[3]} first_at={r[4]} cnt={r[5]}")


asyncio.run(query())
