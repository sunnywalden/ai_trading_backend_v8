"""
一次性回填脚本: 修复 TradeJournal 中 entry_price=0.0 / quantity=0.0 的历史记录
从同 account_id+symbol 的最近一条 AI_AUTONOMOUS TradingPlan 中取真实价格。
"""
import asyncio
import os
import sys
from decimal import Decimal
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, and_, update, desc
from app.models.db import SessionLocal
from app.models.trade_journal import TradeJournal
from app.models.trading_plan import TradingPlan


async def backfill():
    async with SessionLocal() as session:
        # 找出所有 entry_price == 0 且 journal_status == FAILED 的日志（撤单补建的）
        bad_journals_res = await session.execute(
            select(TradeJournal).where(
                and_(
                    TradeJournal.entry_price == 0,
                    TradeJournal.journal_status == "FAILED",
                )
            ).order_by(desc(TradeJournal.created_at))
        )
        bad_journals = bad_journals_res.scalars().all()
        print(f"Found {len(bad_journals)} journal records with entry_price=0 to backfill")

        updated = 0
        skipped = 0

        for j in bad_journals:
            # 查找同 account + symbol 最近的 AI_AUTONOMOUS 计划
            plan_res = await session.execute(
                select(TradingPlan).where(
                    and_(
                        TradingPlan.account_id == j.account_id,
                        TradingPlan.symbol == j.symbol,
                        TradingPlan.source == "AI_AUTONOMOUS",
                    )
                ).order_by(desc(TradingPlan.created_at)).limit(1)
            )
            plan = plan_res.scalar_one_or_none()

            if plan and plan.entry_price and float(plan.entry_price) > 0:
                actual_entry = Decimal(str(plan.entry_price))
                actual_qty   = Decimal(str(plan.target_position)) if plan.target_position else Decimal("0")
                j.entry_price = actual_entry  # type: ignore[assignment]
                j.quantity    = actual_qty    # type: ignore[assignment]
                if j.plan_id is None:
                    j.plan_id = plan.id       # type: ignore[assignment]
                print(f"  ✓ journal#{j.id} {j.symbol} {j.direction}: "
                      f"entry_price={float(actual_entry)}, qty={float(actual_qty)}, plan_id={plan.id}")
                updated += 1
            else:
                print(f"  ✗ journal#{j.id} {j.symbol}: no matching AI_AUTONOMOUS plan with price > 0, skipping")
                skipped += 1

        if updated > 0:
            await session.commit()

        print(f"\nDone: updated={updated}, skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(backfill())
