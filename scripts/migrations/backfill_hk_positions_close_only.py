"""Targeted backfill for HK positions that have ONLY a SELL intent (no BUY recorded).

Background
----------
Positions 06862 (HAIDILAO) and 03454 (CSOP MAG7 ETF) were opened BEFORE the
Position-lifecycle feature (v10.4.4) existed, so no ``positions`` table record was
ever written for them.  When they were eventually closed (2026-03-09) the engine
called ``_integrate_position_lifecycle`` but found no matching open position and
silently skipped, leaving the lifecycle panel empty.

This script reconstructs a CLOSED position record from the SELL execution intent,
optionally fetching the entry price from the corresponding ``trading_plan`` row.

Usage
-----
    # Dry-run (default – prints plan, touches nothing):
    python scripts/migrations/backfill_hk_positions_close_only.py

    # Actually write to DB:
    python scripts/migrations/backfill_hk_positions_close_only.py --execute

    # Limit to a specific account:
    python scripts/migrations/backfill_hk_positions_close_only.py --execute \\
        --account-id 21272246230273657

Idempotency
-----------
The script checks for an existing ``positions`` row with
``(account_id, symbol, thesis_key='default')`` before inserting.  Re-running is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.execution_slice import ExecutionSlice, SliceAction, SliceStatus
from app.models.position import ClosingReason, ExecutionPath, Position, PositionStatus

# ── Symbols to backfill ────────────────────────────────────────────────────────
TARGET_SYMBOLS = {"06862", "03454"}
THESIS_KEY = "default"


async def _backfill(
    db: AsyncSession,
    dry_run: bool,
    account_id_filter: str | None,
) -> None:
    print(f"[Backfill] dry_run={dry_run}  account_id_filter={account_id_filter!r}")

    # ── 1. Load SELL intents for target symbols ────────────────────────────────
    stmt = (
        select(AutonomousExecutionIntent)
        .where(
            AutonomousExecutionIntent.symbol.in_(TARGET_SYMBOLS),
            AutonomousExecutionIntent.action.in_(["SELL", "EXIT", "CLOSE", "REDUCE"]),
            AutonomousExecutionIntent.status == "SUCCESS",
        )
        .order_by(AutonomousExecutionIntent.created_at.asc())
    )
    if account_id_filter:
        stmt = stmt.where(
            AutonomousExecutionIntent.account_id == account_id_filter
        )
    result = await db.execute(stmt)
    intents: list[AutonomousExecutionIntent] = list(result.scalars().all())
    print(f"[Backfill] Found {len(intents)} SELL intent(s) for {TARGET_SYMBOLS}")

    if not intents:
        print("[Backfill] Nothing to do.")
        return

    # ── 2. Check which (account, symbol) already have a position ──────────────
    existing_stmt = select(
        Position.account_id, Position.symbol, Position.thesis_key
    ).where(
        Position.symbol.in_(TARGET_SYMBOLS),
        Position.thesis_key == THESIS_KEY,
    )
    existing_result = await db.execute(existing_stmt)
    existing_keys = {
        (r.account_id, r.symbol, r.thesis_key) for r in existing_result
    }
    if existing_keys:
        print(f"[Backfill] Already-existing positions: {existing_keys}")

    # ── 3. Collect trading_plan entry prices (keyed by plan id) ───────────────
    plan_ids = {i.signal_db_id for i in intents if i.signal_db_id}
    plan_entry_prices: dict[int, float | None] = {}
    if plan_ids:
        try:
            rows = await db.execute(
                text(
                    "SELECT id, entry_price FROM trading_plan "
                    f"WHERE id IN ({','.join(str(p) for p in plan_ids)})"
                )
            )
            for row in rows:
                plan_entry_prices[row[0]] = row[1]
            print(f"[Backfill] trading_plan entry prices: {plan_entry_prices}")
        except Exception as exc:
            print(f"[Backfill] WARN: could not fetch trading_plan: {exc}")

    # ── 4. Group by (account_id, symbol) ──────────────────────────────────────
    from collections import defaultdict

    groups: dict[tuple[str, str], list[AutonomousExecutionIntent]] = defaultdict(list)
    for intent in intents:
        groups[(intent.account_id, intent.symbol)].append(intent)

    created_positions = 0
    created_slices = 0
    skipped = 0

    for (acc, sym), group in sorted(groups.items()):
        key = (acc, sym, THESIS_KEY)
        if key in existing_keys:
            print(f"  [SKIP] {acc}/{sym} – position already exists")
            skipped += 1
            continue

        closed_qty = sum(i.qty or 0.0 for i in group)
        closed_at = group[-1].created_at
        entry_price: float | None = None
        # Try to get from trading_plan via signal_db_id of the last intent
        for intent in group:
            if intent.signal_db_id and intent.signal_db_id in plan_entry_prices:
                entry_price = plan_entry_prices[intent.signal_db_id]
                break

        print(
            f"  {'[DRY]' if dry_run else '[CREATE]'} Position {acc}/{sym}  "
            f"status=CLOSED  qty={closed_qty}  entry_price={entry_price}  "
            f"closed_at={closed_at}"
        )

        if dry_run:
            continue

        # ── Insert Position ────────────────────────────────────────────────────
        pos = Position(
            account_id=acc,
            symbol=sym,
            thesis_key=THESIS_KEY,
            status=PositionStatus.CLOSED.value,
            direction="LONG",
            total_qty=closed_qty,
            filled_qty=closed_qty,
            open_qty=0.0,
            closed_qty=closed_qty,
            avg_entry_price=entry_price,
            # opened_at unknown (pre-lifecycle era)
            closed_at=closed_at,
            last_action_at=closed_at,
            closing_reason=ClosingReason.VOLITIONAL.value,
        )
        db.add(pos)
        await db.flush()  # get pos.id

        # ── Insert ExecutionSlice for each SELL intent ─────────────────────────
        for idx, intent in enumerate(group):
            slc = ExecutionSlice(
                position_id=pos.id,
                account_id=acc,
                symbol=sym,
                action=SliceAction.CLOSE.value,
                status=SliceStatus.FILLED.value,
                requested_qty=intent.qty or 0.0,
                submitted_qty=intent.qty or 0.0,
                filled_qty=intent.qty or 0.0,
                closing_reason=ClosingReason.VOLITIONAL.value,
                signal_id=intent.signal_id,
                signal_db_id=intent.signal_db_id,
                intent_id=intent.intent_id,
                execution_path=ExecutionPath.AUTONOMOUS.value,
                order_ids=[intent.order_id] if intent.order_id else None,
            )
            db.add(slc)
            await db.flush()  # get slc.id

            # Back-link intent → position + slice
            intent.position_id = pos.id
            intent.execution_slice_id = slc.id
            db.add(intent)
            created_slices += 1

        created_positions += 1
        print(f"    → Position id={pos.id} created with {len(group)} close slice(s)")

    if not dry_run:
        await db.commit()
        print(
            f"\n[Backfill] Committed. "
            f"positions_created={created_positions}  "
            f"slices_created={created_slices}  skipped={skipped}"
        )
    else:
        print(
            f"\n[Backfill] Dry-run complete (nothing written). "
            f"Would create {len(groups) - skipped} position(s), {len(intents)} slice(s). "
            f"Skipped {skipped}."
        )
        print("\nRe-run with --execute to apply changes.")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill CLOSED positions for HK stocks that have only SELL intents."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually write to DB (default is dry-run).",
    )
    parser.add_argument(
        "--account-id",
        default=None,
        help="Restrict to a specific account_id.",
    )
    args = parser.parse_args()

    dry = not args.execute

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        await _backfill(db, dry_run=dry, account_id_filter=args.account_id)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
