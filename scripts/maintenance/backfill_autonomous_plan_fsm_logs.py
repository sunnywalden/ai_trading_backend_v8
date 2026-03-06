from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import os
import sys
from datetime import date, datetime, timezone

from sqlalchemy import and_, desc, func, select

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.db import SessionLocal
from app.models.trading_plan import TradingPlan
from app.models.fsm_transition_log import FsmTransitionLog


async def main():
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

    async with SessionLocal() as s:
        plans = list((await s.execute(
            select(TradingPlan)
            .where(
                and_(
                    TradingPlan.source == "AI_AUTONOMOUS",
                    TradingPlan.updated_at >= today_start,
                    TradingPlan.pipeline_stage == 7,
                    TradingPlan.plan_status == "EXECUTED",
                )
            )
            .order_by(desc(TradingPlan.updated_at))
        )).scalars().all())

        created = 0
        skipped = 0

        for p in plans:
            exists = (await s.execute(
                select(func.count(FsmTransitionLog.id)).where(
                    and_(
                        FsmTransitionLog.plan_id == p.id,
                        FsmTransitionLog.fsm_type == "PLAN",
                        FsmTransitionLog.to_state == "STAGE_7",
                    )
                )
            )).scalar() or 0

            if exists > 0:
                skipped += 1
                continue

            s.add(FsmTransitionLog(
                plan_id=p.id,
                fsm_type="PLAN",
                from_state="UNKNOWN",
                to_state="STAGE_7",
                engine="autonomous",
                trigger_reason=f"Autonomous execution backfill: plan#{p.id} {p.symbol}",
            ))
            created += 1

        if created > 0:
            await s.commit()

        print(f"Done: plans={len(plans)}, created={created}, skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
