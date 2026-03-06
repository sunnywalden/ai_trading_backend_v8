import asyncio
import os
import sys
from datetime import date

from sqlalchemy import desc, select

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.db import SessionLocal
from app.models.trading_plan import TradingPlan
from app.models.fsm_transition_log import FsmTransitionLog
from app.services.journal_service import JournalService


TARGET = {"META", "ORCL", "AVGO", "INTC", "AMZN", "CRM"}


async def main():
    async with SessionLocal() as s:
        # 取最近自主计划对应账户
        latest_plan = (await s.execute(
            select(TradingPlan).where(TradingPlan.source == "AI_AUTONOMOUS").order_by(desc(TradingPlan.id)).limit(1)
        )).scalar_one_or_none()
        if not latest_plan:
            print("No autonomous plans found")
            return
        account_id = latest_plan.account_id
        print("account_id=", account_id)

        # 1) 校验生命周期事件（最近 50 条 PLAN）
        ev_rows = (await s.execute(
            select(FsmTransitionLog.plan_id, FsmTransitionLog.from_state, FsmTransitionLog.to_state, FsmTransitionLog.trigger_reason, TradingPlan.symbol)
            .join(TradingPlan, TradingPlan.id == FsmTransitionLog.plan_id)
            .where(FsmTransitionLog.fsm_type == "PLAN")
            .order_by(desc(FsmTransitionLog.occurred_at), desc(FsmTransitionLog.id))
            .limit(50)
        )).all()

        hit_symbols = [r.symbol for r in ev_rows if r.symbol in TARGET]
        print("lifecycle_recent_hits=", hit_symbols)

        # 2) 校验交易日志第一页（走服务层过滤/排序逻辑）
        svc = JournalService(s)
        journals, total = await svc.list_journals(account_id=account_id, page=1, size=20)
        top = [(j.id, j.symbol, j.journal_status) for j in journals[:20]]
        print("journal_total=", total)
        print("journal_page1=", top)

        completed_targets = {j.symbol for j in journals if j.symbol in TARGET and (j.journal_status or "").upper() == "COMPLETED"}
        print("completed_targets_in_page1=", sorted(completed_targets))


if __name__ == "__main__":
    asyncio.run(main())
