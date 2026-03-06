import asyncio
import json

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.trading_plan import TradingPlan

IDS = (49, 50, 53)

async def main() -> None:
    async with SessionLocal() as db:
        plans = (
            await db.execute(select(TradingPlan).where(TradingPlan.id.in_(IDS)).order_by(TradingPlan.id.asc()))
        ).scalars().all()
    print(json.dumps([
        {
            "id": p.id,
            "symbol": p.symbol,
            "plan_status": p.plan_status,
            "pipeline_stage": p.pipeline_stage,
            "position_fsm_state": p.position_fsm_state,
            "updated_at": str(p.updated_at),
        }
        for p in plans
    ], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
