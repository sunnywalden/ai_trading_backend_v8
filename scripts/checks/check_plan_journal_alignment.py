import asyncio
import os
import sys
from datetime import date, datetime, timezone

from sqlalchemy import and_, desc, select

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.db import SessionLocal
from app.models.trade_journal import TradeJournal
from app.models.trading_plan import TradingPlan


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
                )
            )
            .order_by(desc(TradingPlan.updated_at))
        )).scalars().all())

        print(f"Autonomous plans today: {len(plans)}")
        for p in plans:
            journals = list((await s.execute(
                select(TradeJournal)
                .where(
                    and_(
                        TradeJournal.account_id == p.account_id,
                        TradeJournal.symbol == p.symbol,
                        TradeJournal.entry_date == today,
                    )
                )
                .order_by(desc(TradeJournal.id))
            )).scalars().all())

            j_statuses = [(j.id, j.journal_status, j.plan_id) for j in journals]
            print(
                f"plan#{p.id} {p.symbol} status={p.plan_status} stage={p.pipeline_stage} -> journals={j_statuses[:3]}"
            )


if __name__ == "__main__":
    asyncio.run(main())
