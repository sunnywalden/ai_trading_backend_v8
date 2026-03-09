import asyncio
import sys
import os

sys.path.insert(0, '.')
os.environ.setdefault('ENV', 'production')

from sqlalchemy import text
from app.models.db import SessionLocal


async def query():
    async with SessionLocal() as session:
        # 从 trading_plan 查 06862/03454
        result = await session.execute(text(
            "SELECT id, account_id, symbol, action, qty, plan_status, entry_price, current_price, created_at "
            "FROM trading_plan WHERE symbol IN ('06862', '03454') ORDER BY symbol, created_at LIMIT 30"
        ))
        rows = result.fetchall()
        print(f"trading_plan rows: {len(rows)}")
        for r in rows:
            print(f"  [{r.symbol}] action={r.action} qty={r.qty} status={r.plan_status} entry={r.entry_price} created={r.created_at}")

        # 查哪些表存在
        result_tables = await session.execute(text("SHOW TABLES"))
        all_tables = [row[0] for row in result_tables.fetchall()]
        print(f"\nAll tables: {all_tables}")

        # 从 autonomous_execution_intent 查所有記录（所有状态）
        result4 = await session.execute(text(
            "SELECT id, account_id, symbol, action, qty, status, order_id, intent_id, created_at "
            "FROM autonomous_execution_intent WHERE symbol IN ('06862', '03454') ORDER BY symbol, created_at LIMIT 50"
        ))
        rows4 = result4.fetchall()
        print(f"\nautonomous_execution_intent rows: {len(rows4)}")
        for r in rows4:
            print(f"  [{r.symbol}] action={r.action} qty={r.qty} status={r.status} order_id={r.order_id} created={r.created_at}")


asyncio.run(query())
