
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from app.models.db import SessionLocal
from sqlalchemy import select, and_, or_
from app.models.trading_plan import TradingPlan
from app.models.trading_signal import TradingSignal, SignalStatus
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.strategy import Strategy # Explicit import to resolve ORM mapping
from datetime import datetime, timezone

async def fix():
    async with SessionLocal() as session:
        # 修正：数据库中部分记录 pipeline_stage 为 None，但 Status 为 EXECUTED
        # 这些在前端根据逻辑会被归类到监控中或活跃订单
        # 既然用户今天全部撤销了，我们清理所有这些记录
        
        plans_stmt = select(TradingPlan).where(
            or_(
                TradingPlan.pipeline_stage.in_([7, 8, 12]),
                and_(TradingPlan.pipeline_stage.is_(None), TradingPlan.plan_status == "EXECUTED")
            )
        )
        plans = (await session.execute(plans_stmt)).scalars().all()
        print(f"Force cleaning {len(plans)} plans stuck in Stage 12 (Monitoring)...")
        
        for p in plans:
            old_stage = p.pipeline_stage
            old_status = p.plan_status
            
            p.pipeline_stage = 16 # 已完成 (Archive)
            p.plan_status = "REVOKED" # 设置为已撤回/完成状态
            p.stage_entered_at = datetime.now(timezone.utc).replace(tzinfo=None)
            
            session.add(FsmTransitionLog(
                plan_id=p.id,
                fsm_type="PLAN",
                from_state=f"STAGE_{old_stage}",
                to_state="STAGE_16",
                trigger_reason=f"Manual Cleanup: Clearing stale Stage 12 monitoring data for {p.symbol}"
            ))
            print(f"  - Plan {p.id} ({p.symbol}): {old_status} @ S{old_stage} -> REVOKED @ S16")
            
        await session.commit()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(fix())
