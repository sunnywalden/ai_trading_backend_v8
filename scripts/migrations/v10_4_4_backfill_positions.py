"""V10.4.4 – Backfill Positions from historical AutonomousExecutionIntent records.

Usage:
    cd /path/to/ai_trading_backend_v8
    python scripts/migrations/v10_4_4_backfill_positions.py [--dry-run] [--account-id ACCOUNT_ID]

What it does:
1. Reads all AutonomousExecutionIntent rows with status='SUCCESS'.
2. Groups by (account_id, symbol) to construct Position records.
3. For each group:
   - The first ENTRY/BUY intent becomes the Position opener.
   - Subsequent ADD intents become ADD slices.
   - EXIT/SELL intents become CLOSE/REDUCE slices.
4. Positions with a matching EXIT/SELL are marked CLOSED; open groups stay ACTIVE.
5. Creates corresponding ExecutionSlice records.
6. Skips any (account_id, symbol) that already has a Position in DB.
7. Does NOT create PositionLifecycleEvent rows (historical data is sparse).

Dry-run mode prints the plan without writing to DB.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.execution_slice import ExecutionSlice, SliceAction, SliceStatus
from app.models.position import ClosingReason, ExecutionPath, Position, PositionStatus


def _utcnow() -> datetime:
    return datetime.utcnow()


async def _backfill(
    db: AsyncSession,
    dry_run: bool = True,
    account_id_filter: Optional[str] = None,
) -> None:
    print(f"[Backfill] dry_run={dry_run} account_id_filter={account_id_filter!r}")

    # Load all SUCCESS intents
    stmt = (
        select(AutonomousExecutionIntent)
        .where(AutonomousExecutionIntent.status == "SUCCESS")
        .order_by(AutonomousExecutionIntent.created_at.asc())
    )
    if account_id_filter:
        stmt = stmt.where(AutonomousExecutionIntent.account_id == account_id_filter)
    result = await db.execute(stmt)
    intents = result.scalars().all()
    print(f"[Backfill] Loaded {len(intents)} SUCCESS intents")

    # Check which symbols already have a Position
    existing_stmt = select(Position.account_id, Position.symbol, Position.thesis_key)
    existing_result = await db.execute(existing_stmt)
    existing_keys = {(r.account_id, r.symbol, r.thesis_key) for r in existing_result}
    print(
        f"[Backfill] {len(existing_keys)} (account,symbol,thesis_key) already have positions"
    )

    # Group intents by (account_id, symbol) preserving order
    from collections import defaultdict

    groups: dict[tuple[str, str], list[AutonomousExecutionIntent]] = defaultdict(list)
    for intent in intents:
        groups[(intent.account_id, intent.symbol)].append(intent)

    created_positions = 0
    created_slices = 0
    skipped = 0

    for (acc, sym), group in sorted(groups.items()):
        key = (acc, sym, "default")
        if key in existing_keys:
            skipped += 1
            continue

        entries = [
            i
            for i in group
            if (i.action or "").upper() in ("BUY", "LONG", "ENTRY", "ADD")
        ]
        exits = [
            i
            for i in group
            if (i.action or "").upper() in ("SELL", "SHORT", "EXIT", "REDUCE", "CLOSE")
        ]

        if not entries:
            # Pure exit-only history – skip (no meaningful position)
            skipped += 1
            continue

        first = entries[0]
        is_closed = bool(exits)
        closed_at = exits[-1].created_at if exits else None
        exec_path = (
            (first.execution_path or ExecutionPath.AUTONOMOUS.value)
            if hasattr(first, "execution_path")
            else ExecutionPath.AUTONOMOUS.value
        )

        pos_status = (
            PositionStatus.CLOSED.value if is_closed else PositionStatus.ACTIVE.value
        )
        pos_dir = (
            "LONG"
            if (first.action or "").upper() in ("BUY", "LONG", "ENTRY")
            else "SHORT"
        )

        total_qty = sum(i.qty or 0 for i in entries)
        closed_qty = sum(i.qty or 0 for i in exits)
        open_qty = max(0.0, total_qty - closed_qty)

        print(
            f"  {'[DRY]' if dry_run else '[CREATE]'} Position {acc}/{sym} "
            f"status={pos_status} qty={total_qty} closed={closed_qty} path={exec_path}"
        )

        if not dry_run:
            pos = Position(
                account_id=acc,
                symbol=sym,
                thesis_key="default",
                status=pos_status,
                direction=pos_dir,
                execution_path=exec_path,
                total_qty=total_qty,
                filled_qty=total_qty,
                open_qty=open_qty,
                closed_qty=closed_qty,
                initial_signal_id=first.signal_db_id,
                initial_signal_uid=first.signal_id,
                opened_at=first.created_at,
                closed_at=closed_at,
                last_action_at=closed_at or first.created_at,
                closing_reason=(ClosingReason.VOLITIONAL.value if is_closed else None),
            )
            db.add(pos)
            await db.flush()

            # Create slices for ENTRY
            for intent in entries:
                slc_action = (
                    SliceAction.OPEN.value if intent == first else SliceAction.ADD.value
                )
                slc = ExecutionSlice(
                    position_id=pos.id,
                    account_id=acc,
                    symbol=sym,
                    action=slc_action,
                    status=SliceStatus.FILLED.value,
                    requested_qty=intent.qty or 0,
                    submitted_qty=intent.qty or 0,
                    filled_qty=intent.qty or 0,
                    signal_id=intent.signal_id,
                    signal_db_id=intent.signal_db_id,
                    intent_id=intent.intent_id,
                    execution_path=exec_path,
                )
                db.add(slc)
                intent.position_id = pos.id
                created_slices += 1

            # Create slices for EXIT
            for intent in exits:
                slc = ExecutionSlice(
                    position_id=pos.id,
                    account_id=acc,
                    symbol=sym,
                    action=SliceAction.CLOSE.value,
                    status=SliceStatus.FILLED.value,
                    requested_qty=intent.qty or 0,
                    submitted_qty=intent.qty or 0,
                    filled_qty=intent.qty or 0,
                    closing_reason=ClosingReason.VOLITIONAL.value,
                    signal_id=intent.signal_id,
                    signal_db_id=intent.signal_db_id,
                    intent_id=intent.intent_id,
                    execution_path=exec_path,
                )
                db.add(slc)
                intent.position_id = pos.id
                created_slices += 1

            created_positions += 1

    if not dry_run:
        await db.commit()

    print(
        f"\n[Backfill] Done. positions_created={created_positions} "
        f"slices_created={created_slices} skipped={skipped}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument("--account-id", default=None)
    args = parser.parse_args()

    dry = not args.execute

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        await _backfill(db, dry_run=dry, account_id_filter=args.account_id)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
