"""深度诊断：追踪 actual_return 无法回填的具体断点"""
import asyncio
import sys
sys.path.insert(0, "/Users/admin/IdeaProjects/ai_trading_backend_v8")

import app.models.strategy  # noqa
from sqlalchemy import select, func, and_, or_, text
from app.models.db import SessionLocal
from app.models.trading_signal import TradingSignal
from app.models.trade_journal import TradeJournal
from app.models.trading_plan import TradingPlan


async def main():
    async with SessionLocal() as db:
        print("=== TradingSignal 字段 ===")
        sig_cols = [c.name for c in TradingSignal.__table__.columns]
        print(f"  所有列: {sig_cols}")

        print("\n=== TradeJournal COMPLETED 样本（5条）===")
        rows = (await db.execute(
            select(
                TradeJournal.id, TradeJournal.symbol, TradeJournal.journal_status,
                TradeJournal.signal_id, TradeJournal.plan_id,
                TradeJournal.entry_price, TradeJournal.exit_price,
                TradeJournal.realized_pnl
            )
            .where(TradeJournal.journal_status.in_(["COMPLETED", "CLOSED", "DONE"]))
            .limit(5)
        )).all()
        for r in rows:
            print(f"  id={r.id} {r.symbol} status={r.journal_status} signal_id={r.signal_id} plan_id={r.plan_id}")
            print(f"    entry={r.entry_price} exit={r.exit_price} realized_pnl={r.realized_pnl}")

        print("\n=== COMPLETED journals: 有 exit_price 的数量 ===")
        completed_with_exit = (await db.execute(
            select(func.count()).select_from(TradeJournal)
            .where(
                TradeJournal.journal_status.in_(["COMPLETED", "CLOSED", "DONE"]),
                TradeJournal.exit_price.is_not(None),
            )
        )).scalar() or 0
        completed_total = (await db.execute(
            select(func.count()).select_from(TradeJournal)
            .where(TradeJournal.journal_status.in_(["COMPLETED", "CLOSED", "DONE"]))
        )).scalar() or 0
        print(f"  COMPLETED/CLOSED: total={completed_total}, with_exit_price={completed_with_exit}")

        print("\n=== M1 JOIN 能匹配到的记录 ===")
        match_rows = (await db.execute(
            select(
                TradingSignal.id,
                TradingSignal.signal_id.label("sig_signal_id"),
                TradeJournal.signal_id.label("j_signal_id"),
                TradeJournal.entry_price,
                TradeJournal.exit_price,
            )
            .join(
                TradeJournal,
                and_(
                    TradingSignal.signal_id == TradeJournal.signal_id,
                    TradeJournal.journal_status.in_(["CLOSED", "COMPLETED", "DONE"]),
                    TradeJournal.exit_price.isnot(None),
                    TradeJournal.entry_price.isnot(None),
                    TradeJournal.entry_price != 0,
                ),
            )
            .where(TradingSignal.actual_return.is_(None))
            .limit(10)
        )).all()
        print(f"  M1 JOIN 能匹配 {len(match_rows)} 条 → 执行回填后可填入 actual_return")
        for r in match_rows[:3]:
            print(f"  sig_id={r.sig_signal_id} j_signal_id={r.j_signal_id} entry={r.entry_price} exit={r.exit_price}")

        print("\n=== TradingPlan 与 TradeJournal 关联情况 ===")
        # 通过 plan_id 关联
        plans_with_journal = (await db.execute(
            select(func.count()).select_from(TradingPlan)
            .where(
                TradingPlan.id.in_(
                    select(TradeJournal.plan_id).where(TradeJournal.plan_id.is_not(None))
                )
            )
        )).scalar() or 0
        print(f"  通过 plan_id 关联到 journal 的 plans: {plans_with_journal}")

        print("\n=== DRAFT journal 样本（了解为何卡在 DRAFT）===")
        draft_rows = (await db.execute(
            select(
                TradeJournal.id, TradeJournal.symbol, TradeJournal.journal_status,
                TradeJournal.signal_id, TradeJournal.plan_id,
                TradeJournal.entry_price, TradeJournal.exit_price,
            ).where(TradeJournal.journal_status == "DRAFT").limit(5)
        )).all()
        for r in draft_rows:
            print(f"  id={r.id} {r.symbol} signal_id={r.signal_id} plan_id={r.plan_id} entry={r.entry_price} exit={r.exit_price}")

        print("\n=== TradingSignal account_id 字段确认 ===")
        sig_acct = (await db.execute(
            select(TradingSignal.account_id if hasattr(TradingSignal, 'account_id') else text("'N/A'"),
                   func.count().label("cnt"))
            .group_by(text("1"))
            .limit(5)
        )).all()
        print(f"  signal account dist: {[(r[0], r[1]) for r in sig_acct]}")


asyncio.run(main())
