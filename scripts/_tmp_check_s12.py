import asyncio, app.models.strategy
from sqlalchemy import select, func
from app.models.db import SessionLocal
from app.models.trading_plan import TradingPlan

async def main():
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(TradingPlan.plan_status, TradingPlan.pipeline_stage, func.count().label('cnt'))
            .where(TradingPlan.pipeline_stage.in_([12,13,14,15]))
            .group_by(TradingPlan.plan_status, TradingPlan.pipeline_stage)
            .order_by(TradingPlan.pipeline_stage, func.count().desc())
        )).all()
        for r in rows:
            print(f'  S{r.pipeline_stage} status={r.plan_status!r} cnt={r.cnt}')

asyncio.run(main())
