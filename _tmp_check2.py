import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

DB_URL = "mysql+aiomysql://ai_trading:YourStrong%40Passw0rd!@127.0.0.1:3306/ai_trading"

async def main():
    engine = create_async_engine(DB_URL)
    async with AsyncSession(engine) as db:
        r = await db.execute(text("SELECT id, symbol, plan_status, pipeline_stage FROM trading_plan WHERE id IN (844,845)"))
        print("trading_plan rows:", r.fetchall())

        r2 = await db.execute(text("SELECT id, symbol, status, closed_at FROM positions WHERE symbol IN ('06862','03454')"))
        print("positions:", r2.fetchall())

        r3 = await db.execute(text("SELECT id, position_id, symbol, action, status FROM execution_slices ORDER BY id DESC LIMIT 5"))
        print("slices:", r3.fetchall())

asyncio.run(main())
