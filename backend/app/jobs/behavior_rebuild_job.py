import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.services.behavior_scoring_service import BehaviorScoringService

DATABASE_URL = "sqlite+aiosqlite:///./demo.db"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def main():
    account_id = settings.TIGER_ACCOUNT
    window_days = 60
    async with SessionLocal() as session:
        svc = BehaviorScoringService(session)
        metrics = await svc.run_for_account(account_id, window_days, as_of=datetime.utcnow())
        print(f"[BehaviorRebuildJob] account={account_id} window_days={window_days} symbols={list(metrics.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
