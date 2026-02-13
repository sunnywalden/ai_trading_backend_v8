import asyncio
from sqlalchemy import select
from app.models.db import SessionLocal
from app.models.position_score import PositionScore

from app.models.fundamental_data import FundamentalData

async def check():
    async with SessionLocal() as session:
        print("--- FundamentalData ---")
        stmt = select(FundamentalData).order_by(FundamentalData.fiscal_date.desc()).limit(5)
        result = await session.execute(stmt)
        for s in result.scalars():
             print(f"Symbol: {s.symbol}, Sector: {s.sector}, Beta: {s.beta}")

        print("\n--- PositionScore ---")
        stmt = select(PositionScore).order_by(PositionScore.timestamp.desc()).limit(10)
        result = await session.execute(stmt)
        scores = result.scalars().all()
        for s in scores:
            print(f"Symbol: {s.symbol}, Score: {s.overall_score}, Sector: {s.sector}, Industry: {s.industry}, Beta: {s.beta}")

if __name__ == "__main__":
    asyncio.run(check())
