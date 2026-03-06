import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.db import SessionLocal
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.trading_plan import TradingPlan

TARGETS = {
    49: {"status": "EXPIRED", "reason": "broker-manual-cancel-sync(Order is expired)"},
    50: {"status": "EXPIRED", "reason": "broker-manual-cancel-sync(Order is expired)"},
    53: {"status": "FAILED", "reason": "broker-manual-cancel-sync(The order quantity you entered exceeds your current holdings; If you'd like to sell-to-open, please close your positions beforehand.)"},
}


async def main() -> None:
    now = datetime.now(timezone.utc)
    out = {"before": [], "after": []}
    async with SessionLocal() as db:
        plans = (
            await db.execute(
                select(TradingPlan).where(TradingPlan.id.in_(tuple(TARGETS.keys()))).order_by(TradingPlan.id.asc())
            )
        ).scalars().all()

        for plan in plans:
            out["before"].append({
                "id": plan.id,
                "symbol": plan.symbol,
                "plan_status": plan.plan_status,
                "pipeline_stage": plan.pipeline_stage,
                "position_fsm_state": plan.position_fsm_state,
                "updated_at": str(plan.updated_at),
            })

        changed = 0
        for plan in plans:
            target = TARGETS[plan.id]
            desired_status = target["status"]
            changed_any = False
            if plan.pipeline_stage != 16:
                old_stage = plan.pipeline_stage
                plan.pipeline_stage = 16
                plan.stage_entered_at = now
                db.add(FsmTransitionLog(
                    plan_id=plan.id,
                    fsm_type="PLAN",
                    from_state=f"STAGE_{old_stage}" if old_stage is not None else "UNKNOWN",
                    to_state="STAGE_16",
                    trigger_reason=f"Manual reconcile terminal status: {target['reason']}",
                ))
                changed_any = True
            if plan.position_fsm_state != "CLOSED":
                plan.position_fsm_state = "CLOSED"
                changed_any = True
            if plan.plan_status != desired_status:
                plan.plan_status = desired_status
                changed_any = True
            if changed_any:
                changed += 1

        if changed:
            await db.commit()
        else:
            await db.rollback()

        refreshed = (
            await db.execute(
                select(TradingPlan).where(TradingPlan.id.in_(tuple(TARGETS.keys()))).order_by(TradingPlan.id.asc())
            )
        ).scalars().all()
        for plan in refreshed:
            out["after"].append({
                "id": plan.id,
                "symbol": plan.symbol,
                "plan_status": plan.plan_status,
                "pipeline_stage": plan.pipeline_stage,
                "position_fsm_state": plan.position_fsm_state,
                "updated_at": str(plan.updated_at),
            })
        out["changed"] = changed

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
