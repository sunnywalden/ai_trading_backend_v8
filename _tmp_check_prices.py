import asyncio
import sys
sys.path.insert(0, '/Users/admin/IdeaProjects/ai_trading_backend_v8')
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        r = await db.execute(text(
            "SELECT id, symbol, status, direction, open_qty, total_qty, closed_qty, avg_entry_price, opened_at "
            "FROM positions ORDER BY id"
        ))
        rows = r.fetchall()
        print(f"positions table ({len(rows)} rows):")
        for row in rows:
            print(f"  id={row[0]:2d}  {row[1]:6s}  status={row[2]:18s}  dir={row[3]}  open_qty={row[4]:10.4f}  avg_entry={row[7]}")

        r2 = await db.execute(text("SELECT COUNT(*) FROM execution_slices"))
        cnt = r2.scalar()
        print(f"\nexecution_slices: {cnt} rows total")

    await engine.dispose()

asyncio.run(main())
