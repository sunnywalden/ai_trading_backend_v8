"""回填自主交易计划到交易日志（幂等）

用途：修复“活跃计划里有，但交易日志里没有”的历史遗漏。
逻辑：
1) 读取今日 AI_AUTONOMOUS 的 TradingPlan
2) 若同 account_id+symbol 今日无对应 Journal，则补建一条 FAILED/COMPLETED 日志
"""

import asyncio
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import and_, desc, func, select

from app.models.db import SessionLocal
from app.models.trade_journal import TradeJournal
from app.models.trading_plan import TradingPlan


def _infer_journal_status(plan_status: str) -> str:
    s = (plan_status or "").upper()
    if s in {"EXECUTED", "ACTIVE", "AUTO_EXECUTING", "AI_GENERATED", "PENDING_CONFIRM"}:
        return "COMPLETED"
    if s in {"REVOKED", "FAILED", "CANCELLED", "EXPIRED"}:
        return "FAILED"
    return "DRAFT"


async def main() -> None:
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

    async with SessionLocal() as session:
        plan_stmt = (
            select(TradingPlan)
            .where(
                and_(
                    TradingPlan.source == "AI_AUTONOMOUS",
                    TradingPlan.updated_at >= today_start,
                )
            )
            .order_by(desc(TradingPlan.updated_at))
        )
        plans = list((await session.execute(plan_stmt)).scalars().all())
        print(f"Found {len(plans)} autonomous plans updated today")

        created = 0
        updated = 0
        skipped = 0

        for p in plans:
            # 先按 plan_id 做强关联检查
            by_plan_rows = list((await session.execute(
                select(TradeJournal)
                .where(TradeJournal.plan_id == p.id)
                .order_by(desc(TradeJournal.id))
            )).scalars().all())

            # 若计划已执行，但日志没有 COMPLETED：优先把最新一条改为 COMPLETED
            if (p.plan_status or "").upper() == "EXECUTED":
                has_completed = any((r.journal_status or "").upper() == "COMPLETED" for r in by_plan_rows)
                if not has_completed and by_plan_rows:
                    j0 = by_plan_rows[0]
                    j0.journal_status = "COMPLETED"  # type: ignore[assignment]
                    existing_note = str(j0.lesson_learned or "")
                    if existing_note:
                        j0.lesson_learned = f"{existing_note} | 状态对齐: plan#{p.id} EXECUTED"  # type: ignore[assignment]
                    else:
                        j0.lesson_learned = f"状态对齐: plan#{p.id} EXECUTED"  # type: ignore[assignment]
                    updated += 1
                    continue

            # 以 account+symbol+当日 做去重，避免重复刷出很多同类日志
            exists_stmt = select(func.count(TradeJournal.id)).where(
                and_(
                    TradeJournal.account_id == p.account_id,
                    TradeJournal.symbol == p.symbol,
                    TradeJournal.entry_date == today,
                )
            )
            exists = (await session.execute(exists_stmt)).scalar() or 0
            if exists > 0:
                skipped += 1
                continue

            entry_price = Decimal(str(p.entry_price)) if p.entry_price is not None else Decimal("1.0")
            qty = Decimal(str(p.target_position)) if p.target_position is not None else Decimal("0")

            j = TradeJournal(
                account_id=p.account_id,
                symbol=p.symbol,
                direction=p.direction or "BUY",
                entry_date=today,
                entry_price=entry_price,  # type: ignore[assignment]
                quantity=qty,             # type: ignore[assignment]
                plan_id=p.id,             # type: ignore[assignment]
                journal_status=_infer_journal_status(p.plan_status or ""),
                lesson_learned=f"自主计划回填: plan#{p.id} status={p.plan_status}",
            )
            session.add(j)
            created += 1

        if created > 0:
            await session.commit()
        elif updated > 0:
            await session.commit()

        print(f"Done: created={created}, updated={updated}, skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
