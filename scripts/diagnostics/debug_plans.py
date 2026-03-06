
import asyncio
import os
import sys
sys.path.append(os.getcwd())

from app.models.db import SessionLocal
from app.models.trading_plan import TradingPlan
from app.models.strategy import Strategy
from sqlalchemy import select

async def main():
    async with SessionLocal() as session:
        stmt = select(TradingPlan)
        res = await session.execute(stmt)
        plans = res.scalars().all()
        print(f"Total Plans in DB: {len(plans)}")
        for p in plans:
            print(f"ID: {p.id} | Symbol: {p.symbol} | Stage: {p.pipeline_stage} | Status: {p.plan_status}")

if __name__ == "__main__":
    asyncio.run(main())
