"""Reconcile the ``positions`` table against actual broker holdings post-backfill.

Use this script when ``backfill_us_positions_active.py`` has already run but the
lifecycle board still shows mismatches with the broker app:

  * **Ghost positions** – Position records that exist in the lifecycle but the
    broker shows 0 shares (final exit was done outside the autonomous intent
    path).  These should be closed to keep the board accurate.

  * **Missing positions** – Symbols the broker holds that have no ``positions``
    row at all (they were opened via direct TradingPlan execution without an
    ``autonomous_execution_intent`` record).  These should be created as ACTIVE.

Usage
-----
Dry-run (default – prints plan, touches nothing):

    python scripts/migrations/reconcile_positions_with_broker.py \\
        --broker-positions "AMD:2322,FINW:1271,MSFT:100,ORCL:560,PLTR:763,QCOM:853"

Apply changes:

    python scripts/migrations/reconcile_positions_with_broker.py --execute \\
        --broker-positions "AMD:2322,FINW:1271,MSFT:100,ORCL:560,PLTR:763,QCOM:853"

Limit to a specific account:

    python scripts/migrations/reconcile_positions_with_broker.py --execute \\
        --broker-positions "AMD:2322,QCOM:853" \\
        --account-id 21272246230273657

Provide fallback account when some symbols have no DB records:

    python scripts/migrations/reconcile_positions_with_broker.py --execute \\
        --broker-positions "AMD:2322,FINW:1271,MSFT:100,ORCL:560,PLTR:763,QCOM:853" \\
        --fallback-account-id 21272246230273657
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.position import ExecutionPath, Position, PositionStatus

THESIS_KEY = "default"


def _parse_broker_positions(raw: str) -> dict[str, float]:
    if not raw:
        raise ValueError("--broker-positions is required (e.g. AMD:2322,MSFT:100)")
    result: dict[str, float] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(
                f"Invalid entry '{part}'. Expected format: SYMBOL:QTY  (e.g. AMD:2322)"
            )
        sym, qty_str = part.split(":", 1)
        result[sym.strip().upper()] = float(qty_str.strip())
    return result


async def _reconcile(
    db: AsyncSession,
    broker_positions: dict[str, float],
    dry_run: bool,
    account_id_filter: str | None,
    fallback_account_id: str | None,
    sync_quantities: bool,
) -> None:
    now = datetime.now(timezone.utc)
    print(
        f"[Reconcile] dry_run={dry_run}  account_id_filter={account_id_filter!r}  "
        f"fallback_account_id={fallback_account_id!r}\n"
        f"[Reconcile] Broker positions: {broker_positions}"
    )

    broker_syms = set(broker_positions.keys())

    # ── Load all non-terminal lifecycle positions ─────────────────────────────
    stmt = select(Position).where(
        Position.status.notin_(
            [PositionStatus.CLOSED.value, PositionStatus.LIQUIDATED.value]
        ),
        Position.thesis_key == THESIS_KEY,
    )
    if account_id_filter:
        stmt = stmt.where(Position.account_id == account_id_filter)
    result = await db.execute(stmt)
    active_positions: list[Position] = list(result.scalars().all())

    lifecycle_sym_map: dict[str, Position] = {p.symbol: p for p in active_positions}
    print(
        f"\n[Reconcile] Active lifecycle positions ({len(lifecycle_sym_map)}): "
        f"{sorted(lifecycle_sym_map.keys())}"
    )

    # ── 1. Ghost positions: lifecycle OPEN but broker shows 0 ─────────────────
    ghost_syms = set(lifecycle_sym_map.keys()) - broker_syms
    print(
        f"\n[Reconcile] Ghost positions (in lifecycle, broker=0): {sorted(ghost_syms)}"
    )
    for sym in sorted(ghost_syms):
        pos = lifecycle_sym_map[sym]
        print(
            f"  {'[DRY]' if dry_run else '[CLOSE]'} id={pos.id} {sym}  "
            f"current_status={pos.status}  open_qty={pos.open_qty:.4f} → mark CLOSED"
        )
        if not dry_run:
            await db.execute(
                update(Position)
                .where(Position.id == pos.id)
                .values(
                    status=PositionStatus.CLOSED.value,
                    open_qty=0.0,
                    closed_qty=pos.total_qty,
                    closed_at=now,
                    updated_at=now,
                )
            )

    # ── 2. Missing positions: broker holds but no lifecycle record ─────────────
    missing_syms = broker_syms - set(lifecycle_sym_map.keys())
    # Also exclude symbols that already have ANY position (incl. CLOSED)
    if missing_syms:
        already_stmt = select(Position.symbol).where(
            Position.symbol.in_(missing_syms),
            Position.thesis_key == THESIS_KEY,
        )
        if account_id_filter:
            already_stmt = already_stmt.where(Position.account_id == account_id_filter)
        already_result = await db.execute(already_stmt)
        already_have = {r[0] for r in already_result}
        missing_syms -= already_have

    print(
        f"\n[Reconcile] Missing positions (broker>0, no lifecycle record): "
        f"{sorted(missing_syms)}"
    )

    for sym in sorted(missing_syms):
        broker_qty = broker_positions[sym]

        # Attempt to find account_id from trading_plan
        try:
            tp_rows = await db.execute(
                text(
                    "SELECT account_id, entry_price, target_position, created_at "
                    "FROM trading_plan "
                    "WHERE symbol = :sym "
                    "  AND plan_status NOT IN ('REVOKED', 'EXPIRED', 'CANCELLED') "
                    "ORDER BY created_at ASC"
                ),
                {"sym": sym},
            )
            tp_list = list(tp_rows)
        except Exception as exc:
            print(f"  [WARN] trading_plan lookup failed for {sym}: {exc}")
            tp_list = []

        if (
            tp_list
            and fallback_account_id
            and str(tp_list[0][0]) != fallback_account_id
        ):
            # In production there may be multiple accounts; trust explicit override
            pass  # keep tp_list as-is (account from DB is more reliable)

        if not tp_list:
            # Fall back to autonomous_execution_intent for account_id
            try:
                intent_row = await db.execute(
                    text(
                        "SELECT account_id, created_at FROM autonomous_execution_intent "
                        "WHERE symbol = :sym ORDER BY created_at ASC LIMIT 1"
                    ),
                    {"sym": sym},
                )
                intent_data = intent_row.fetchone()
            except Exception as exc:
                print(f"  [WARN] intent lookup failed for {sym}: {exc}")
                intent_data = None

            if intent_data:
                acc = str(intent_data[0])
                opened_at = intent_data[1]
            elif fallback_account_id:
                print(
                    f"  [FALLBACK-ACCOUNT] {sym}  using --fallback-account-id {fallback_account_id!r}"
                )
                acc = fallback_account_id
                opened_at = now
            else:
                print(
                    f"  [SKIP-NO-DATA] {sym}  broker_qty={broker_qty:.4f} "
                    f"- cannot determine account_id; pass --fallback-account-id to override"
                )
                continue
            avg_entry_price = None
        else:
            acc = str(tp_list[0][0])
            opened_at = tp_list[0][3]
            price_valid = [
                (float(r[1]), float(r[2] or 0))
                for r in tp_list
                if r[1] and float(r[1]) > 1.0
            ]
            if price_valid:
                total_w = sum(w for _, w in price_valid)
                avg_entry_price = (
                    sum(p * w for p, w in price_valid) / total_w
                    if total_w > 0
                    else sum(p for p, _ in price_valid) / len(price_valid)
                )
            else:
                avg_entry_price = None

        if account_id_filter and acc != account_id_filter:
            print(
                f"  [SKIP-ACCOUNT] {sym}  account={acc} "
                f"does not match filter {account_id_filter!r}"
            )
            continue

        print(
            f"  {'[DRY]' if dry_run else '[CREATE]'} {acc}/{sym}  "
            f"broker_qty={broker_qty:.4f}  avg_entry={avg_entry_price}  "
            f"opened_at={opened_at}"
        )

        if not dry_run:
            pos = Position(
                account_id=acc,
                symbol=sym,
                thesis_key=THESIS_KEY,
                status=PositionStatus.ACTIVE.value,
                direction="LONG",
                total_qty=broker_qty,
                filled_qty=broker_qty,
                closed_qty=0.0,
                open_qty=broker_qty,
                avg_entry_price=avg_entry_price,
                opened_at=opened_at,
                last_action_at=opened_at,
            )
            db.add(pos)

    # ── 3. Qty correction: lifecycle open_qty differs from broker ─────────────
    # (soft warning only – do not auto-correct to avoid stomping on live engine)
    print("\n[Reconcile] Qty check (lifecycle vs broker):")
    for sym in sorted(broker_syms & set(lifecycle_sym_map.keys())):
        pos = lifecycle_sym_map[sym]
        broker_qty = broker_positions[sym]
        delta = abs(float(pos.open_qty or 0) - broker_qty)
        if delta > 0.5:
            print(
                f"  {'[DRY-QTY]' if dry_run else '[SYNC-QTY]' if sync_quantities else '[QTY-MISMATCH]'} {sym}  "
                f"lifecycle.open_qty={pos.open_qty:.4f}  broker_qty={broker_qty:.4f}  delta={delta:.4f}"
            )
            if not dry_run and sync_quantities:
                new_total_qty = max(float(pos.total_qty or 0.0), broker_qty)
                new_filled_qty = max(float(pos.filled_qty or 0.0), broker_qty)
                await db.execute(
                    update(Position)
                    .where(Position.id == pos.id)
                    .values(
                        status=PositionStatus.ACTIVE.value,
                        open_qty=broker_qty,
                        total_qty=new_total_qty,
                        filled_qty=new_filled_qty,
                        updated_at=now,
                    )
                )
        else:
            print(
                f"  [QTY-OK] {sym}  lifecycle={pos.open_qty:.4f}  "
                f"broker={broker_qty:.4f}"
            )

    if dry_run:
        print(
            "\n[Reconcile] Dry-run complete - nothing written. "
            "Re-run with --execute to apply."
        )
        return

    await db.commit()
    print("\n[Reconcile] Committed.")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile lifecycle positions table against actual broker holdings."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually write to DB (default is dry-run).",
    )
    parser.add_argument(
        "--broker-positions",
        required=True,
        metavar="SYMBOL:QTY,...",
        help=(
            "Actual broker holdings. Format: AMD:2322,FINW:1271,MSFT:100  "
            "Symbols not listed are treated as 0 (fully closed)."
        ),
    )
    parser.add_argument(
        "--account-id",
        default=None,
        help="Restrict to a specific account_id.",
    )
    parser.add_argument(
        "--fallback-account-id",
        default=None,
        metavar="ACCOUNT_ID",
        help=(
            "Fallback account_id for symbols that have no trading_plan/intent data. "
            "Use when broker holds a position that was opened outside all tracked paths."
        ),
    )
    parser.add_argument(
        "--sync-quantities",
        action="store_true",
        default=False,
        help=(
            "When applying changes, also update lifecycle open_qty/total_qty/filled_qty "
            "to match current broker holdings for existing active positions."
        ),
    )
    args = parser.parse_args()

    broker_pos = _parse_broker_positions(args.broker_positions)

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as db:
        await _reconcile(
            db,
            broker_positions=broker_pos,
            dry_run=not args.execute,
            account_id_filter=args.account_id,
            fallback_account_id=args.fallback_account_id,
            sync_quantities=args.sync_quantities,
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
