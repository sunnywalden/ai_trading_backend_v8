
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
from app.models.db import SessionLocal
from sqlalchemy import select, and_
from app.models.trading_plan import TradingPlan
from app.models.fsm_transition_log import FsmTransitionLog
from datetime import datetime, timezone

async def fix():
    async with SessionLocal() as session:
        # 强制将所有阶段为 7 且状态为 EXECUTED 的计划移至阶段 12
        stmt = select(TradingPlan).where(
            and_(
                TradingPlan.pipeline_stage == 7,
                TradingPlan.plan_status == 'EXECUTED'
            )
        )
        plans = (await session.execute(stmt)).scalars().all()
        print(f'Found {len(plans)} plans to sync.')
        
        for p in plans:
            old_stage = p.pipeline_stage
            p.pipeline_stage = 12 # 订单结算
            p.stage_entered_at = datetime.now(timezone.utc).replace(tzinfo=None) # 数据库 DateTime 通常不含时区
            
            session.add(FsmTransitionLog(
                plan_id=p.id,
                fsm_type='PLAN',
                from_state=f'STAGE_{old_stage}' if old_stage is not None else 'UNKNOWN',
                to_state='STAGE_12',
                trigger_reason='Manual cleanup: move finished plans to Stage 12'
            ))
            print(f'  - Plan {p.id} ({p.symbol}) moved to Stage 12')
            
        await session.commit()
        print('DB Update Complete.')

if __name__ == "__main__":
    asyncio.run(fix())
