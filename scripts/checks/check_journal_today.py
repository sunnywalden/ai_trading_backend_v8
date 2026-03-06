from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import os
import sys
from datetime import date

from sqlalchemy import desc, func, select

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.db import SessionLocal
from app.models.trade_journal import TradeJournal


async def main():
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(TradeJournal.symbol, func.count(TradeJournal.id))
                .where(TradeJournal.entry_date == date.today())
                .group_by(TradeJournal.symbol)
                .order_by(TradeJournal.symbol)
            )
        ).all()
        print("Today symbol counts:", rows)

        rec = (
            await s.execute(
                select(
                    TradeJournal.id,
                    TradeJournal.symbol,
                    TradeJournal.journal_status,
                    TradeJournal.entry_price,
                    TradeJournal.plan_id,
                )
                .order_by(desc(TradeJournal.id))
                .limit(30)
            )
        ).all()
        print("Recent journals:")
        for r in rec:
            print(r)


if __name__ == "__main__":
    asyncio.run(main())
