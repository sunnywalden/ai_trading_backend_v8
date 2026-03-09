"""Backfill ACTIVE positions for US stocks that pre-date the Position-centric
lifecycle feature (v10.4.4).

Background
----------
US stocks (e.g. AMZN, AVGO, CRM, META, MSFT, ORCL, QCOM, INTC, TSLA) were
opened BEFORE the ``positions`` table existed.  Their lifecycle is currently
tracked only through ``trading_plan`` + ``autonomous_execution_intent`` records.
As a result, the "仓位总览 · 总计活跃仓位" panel shows 0 even though real
holdings exist.

This script reconstructs an ACTIVE (or PARTIALLY_CLOSED) Position record for
every non-HK symbol that has:
  - At least one ``autonomous_execution_intent`` with action=BUY / status=SUCCESS
  - A net open qty  >  0  (total BUY SUCCESS qty  −  total SELL SUCCESS qty)

Execution slices are created for each underlying BUY intent (action=OPEN) and
each SELL intent (action=CLOSE), so the position-board card's history is correct.

The avg_entry_price is derived as a weighted average from the associated
``trading_plan.entry_price`` values (joined via ``signal_db_id``).

Broker Reconciliation (--broker-positions)
-------------------------------------------
When real broker holdings are provided via ``--broker-positions SYMBOL:QTY,...``
the script performs a two-way reconciliation:

1. **Ghost-position pruning** – any position the script would create that does NOT
   appear in the broker list (qty == 0 in reality) is either skipped entirely (if
   intent net qty is positive) or written as CLOSED.  This handles the common case
   where the final exit was executed outside the autonomous intent path (e.g. manual
   broker order).

2. **Missing-position injection** – any broker symbol NOT covered by intent records
   is reconstructed from ``trading_plan`` EXECUTED records and written as ACTIVE,
   capping ``open_qty`` at the broker's actual share count.  This handles positions
   opened via direct TradingPlan execution without autonomous_execution_intent rows.

Usage
-----
    # Dry-run (default – prints plan, touches nothing):
    python scripts/migrations/backfill_us_positions_active.py

    # Actually write to DB:
    python scripts/migrations/backfill_us_positions_active.py --execute

    # With broker reconciliation (recommended for production):
    python scripts/migrations/backfill_us_positions_active.py --execute \\
        --broker-positions "AMD:2322,FINW:1271,MSFT:100,ORCL:560,PLTR:763,QCOM:853"

    # Limit to specific account:
    python scripts/migrations/backfill_us_positions_active.py --execute \\
        --account-id 21272246230273657

    # Override minimum open-qty threshold (default 0.01):
    python scripts/migrations/backfill_us_positions_active.py --min-qty 1.0

Idempotency
-----------
Before inserting, the script checks for an existing ``positions`` row with
``(account_id, symbol, thesis_key='default')``.  Re-running is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.execution_slice import ExecutionSlice, SliceAction, SliceStatus
from app.models.position import ExecutionPath, Position, PositionStatus

# ── Constants ─────────────────────────────────────────────────────────────────
THESIS_KEY = "default"

# Actions that open a long position
BUY_ACTIONS = frozenset({"BUY", "ENTER", "ADD", "SCALE_IN"})

# Actions that close / reduce a long position
SELL_ACTIONS = frozenset({"SELL", "EXIT", "CLOSE", "REDUCE"})

# Symbols that already have dedicated backfill handled elsewhere (HK stocks)
HK_SYMBOL_PATTERN = r"^[0-9]{5}$"  # 5-digit numeric codes


def _parse_broker_positions(raw: str) -> dict[str, float]:
    """Parse ``--broker-positions 'AMD:2322,MSFT:100'`` into a symbol→qty map.

    Returns an empty dict when *raw* is None / empty.
    """
    if not raw:
        return {}
    result: dict[str, float] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(
                f"Invalid --broker-positions entry '{part}'. "
                "Expected format: SYMBOL:QTY  (e.g. AMD:2322)"
            )
        sym, qty_str = part.split(":", 1)
        result[sym.strip().upper()] = float(qty_str.strip())
    return result


# ─────────────────────────────────────────────────────────────────────────────


async def _backfill(
    db: AsyncSession,
    dry_run: bool,
    account_id_filter: str | None,
    min_qty: float,
    broker_positions: dict[str, float],
) -> None:
    print(
        f"[Backfill] dry_run={dry_run}  account_id_filter={account_id_filter!r}  "
        f"min_qty={min_qty}  broker_positions={broker_positions or '(not provided)'}"
    )

    # ── 1. Load all SUCCESS intents for non-HK symbols ─────────────────────
    stmt = (
        select(AutonomousExecutionIntent)
        .where(
            AutonomousExecutionIntent.status == "SUCCESS",
            AutonomousExecutionIntent.action.in_(
                list(BUY_ACTIONS) + list(SELL_ACTIONS)
            ),
            # Exclude 5-digit HK codes via raw SQL expression
            AutonomousExecutionIntent.symbol.op("NOT REGEXP")(HK_SYMBOL_PATTERN),
        )
        .order_by(
            AutonomousExecutionIntent.account_id,
            AutonomousExecutionIntent.symbol,
            AutonomousExecutionIntent.created_at,
        )
    )
    if account_id_filter:
        stmt = stmt.where(AutonomousExecutionIntent.account_id == account_id_filter)

    result = await db.execute(stmt)
    all_intents: list[AutonomousExecutionIntent] = list(result.scalars().all())
    print(f"[Backfill] Loaded {len(all_intents)} SUCCESS intent(s) for non-HK symbols")

    if not all_intents:
        print("[Backfill] Nothing to do.")
        return

    # ── 2. Group into (account_id, symbol) buckets ─────────────────────────
    buy_intents: dict[tuple[str, str], list[AutonomousExecutionIntent]] = defaultdict(
        list
    )
    sell_intents: dict[tuple[str, str], list[AutonomousExecutionIntent]] = defaultdict(
        list
    )

    for intent in all_intents:
        key = (intent.account_id, intent.symbol)
        if intent.action in BUY_ACTIONS:
            buy_intents[key].append(intent)
        else:
            sell_intents[key].append(intent)

    # ── 3. Check which (account, symbol) already have a position ──────────
    all_symbols = {sym for _, sym in buy_intents.keys()}
    existing_stmt = select(
        Position.account_id, Position.symbol, Position.thesis_key
    ).where(
        Position.symbol.in_(all_symbols),
        Position.thesis_key == THESIS_KEY,
    )
    if account_id_filter:
        existing_stmt = existing_stmt.where(Position.account_id == account_id_filter)
    existing_result = await db.execute(existing_stmt)
    existing_keys = {(r.account_id, r.symbol, r.thesis_key) for r in existing_result}
    if existing_keys:
        print(f"[Backfill] Already-existing positions: {existing_keys}")

    # ── 4. Fetch trading_plan entry prices for weighted-avg cost basis ─────
    # signal_db_id references trading_signals.id (not trading_plan.id), and
    # trading_signals.executed_price / suggested_price are not populated for
    # these autonomous runs.  Instead we group by (account_id, symbol) and
    # average the EXECUTED trading_plan entry_price values (filtering out the
    # $1.00 placeholder prices used by autonomous plans before price discovery).
    symbol_avg_prices: dict[tuple[str, str], float | None] = {}
    all_acct_sym = list(buy_intents.keys())
    if all_acct_sym:
        for acc, sym in all_acct_sym:
            try:
                rows = await db.execute(
                    text(
                        "SELECT entry_price, target_position "
                        "FROM trading_plan "
                        "WHERE account_id = :acc AND symbol = :sym "
                        "  AND entry_price > 1.0 "
                        "  AND plan_status NOT IN ('REVOKED', 'EXPIRED')"
                    ),
                    {"acc": acc, "sym": sym},
                )
                price_rows = list(rows)
                if price_rows:
                    # weighted average by target_position; fall back to simple avg
                    total_weight = sum(
                        float(r[1]) for r in price_rows if r[1] is not None
                    )
                    if total_weight > 0:
                        symbol_avg_prices[(acc, sym)] = (
                            sum(
                                float(r[0]) * float(r[1])
                                for r in price_rows
                                if r[1] is not None
                            )
                            / total_weight
                        )
                    else:
                        symbol_avg_prices[(acc, sym)] = sum(
                            float(r[0]) for r in price_rows
                        ) / len(price_rows)
                else:
                    symbol_avg_prices[(acc, sym)] = None
            except Exception as exc:
                print(f"[Backfill] WARN: price lookup failed for {acc}/{sym}: {exc}")
                symbol_avg_prices[(acc, sym)] = None

    # ── 5. Compute net positions ────────────────────────────────────────────
    positions_to_create: list[dict] = []

    for key, b_intents in sorted(buy_intents.items()):
        acc, sym = key

        if (acc, sym, THESIS_KEY) in existing_keys:
            continue  # already handled by a separate backfill or live engine

        total_buy_qty = sum(i.qty or 0.0 for i in b_intents)
        s_intents = sell_intents.get(key, [])
        total_sell_qty = sum(i.qty or 0.0 for i in s_intents)
        open_qty = total_buy_qty - total_sell_qty

        # ── Broker reconciliation (when --broker-positions is provided) ───────
        # The intent-arithmetic may be stale: some final closes happen outside
        # the autonomous intent path (manual broker orders, direct plan exec, …).
        # When the broker says this symbol is fully closed, honour that truth.
        if broker_positions:
            broker_qty = broker_positions.get(sym.upper(), 0.0)
            if broker_qty <= 0:
                # Broker confirms the position is gone — skip creation entirely.
                # Positions that should be CLOSED are not useful in the lifecycle
                # board; if we must record history, a CLOSED row can be added
                # manually via the repair script.
                print(
                    f"  [SKIP-BROKER] {acc}/{sym}  intent_open_qty={open_qty:.4f} "
                    f"but broker shows 0 — position fully closed out-of-band"
                )
                continue
            # Use broker qty as the authoritative open_qty.
            open_qty = broker_qty
        # ──────────────────────────────────────────────────────────────────────

        if open_qty < min_qty:
            print(
                f"  [SKIP] {acc}/{sym}  open_qty={open_qty:.4f} < min_qty={min_qty} "
                f"(buy={total_buy_qty:.4f}, sell={total_sell_qty:.4f})"
            )
            continue

        # avg_entry_price from trading_plan (weighted average of EXECUTED plans)
        avg_entry_price = symbol_avg_prices.get((acc, sym))

        # Status: PARTIALLY_CLOSED only when there were sells AND open_qty is
        # genuinely less than total buys (not just "any sell exists").
        # When broker data is available, prefer ACTIVE for confirmed holdings.
        if broker_positions:
            status = PositionStatus.ACTIVE.value
        elif total_sell_qty > 0 and open_qty < total_buy_qty * 0.99:
            status = PositionStatus.PARTIALLY_CLOSED.value
        else:
            status = PositionStatus.ACTIVE.value

        opened_at = b_intents[0].created_at  # earliest BUY intent

        positions_to_create.append(
            {
                "acc": acc,
                "sym": sym,
                "status": status,
                "direction": "LONG",
                "total_qty": total_buy_qty,
                "filled_qty": total_buy_qty,
                "closed_qty": total_sell_qty,
                "open_qty": open_qty,
                "avg_entry_price": avg_entry_price,
                "opened_at": opened_at,
                "b_intents": b_intents,
                "s_intents": s_intents,
            }
        )

    # ── 5b. Inject missing positions from trading_plan (broker-guided) ──────
    # When broker_positions lists symbols that have NO autonomous_execution_intent
    # records at all (positions opened via direct TradingPlan execution), reconstruct
    # a minimal ACTIVE Position from trading_plan EXECUTED rows.
    if broker_positions:
        intent_symbols = {sym for _, sym in buy_intents.keys()}
        for sym, broker_qty in broker_positions.items():
            if broker_qty <= 0:
                continue
            if sym in intent_symbols:
                continue  # already handled above
            # Determine account_id from trading_plan records
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

            if not tp_list:
                print(
                    f"  [SKIP-NO-DATA] {sym}  broker_qty={broker_qty:.4f} "
                    f"but no trading_plan records found — add manually"
                )
                continue

            acc = str(tp_list[0][0])
            if account_id_filter and acc != account_id_filter:
                print(
                    f"  [SKIP-ACCOUNT] {sym}  account={acc} "
                    f"does not match filter {account_id_filter!r}"
                )
                continue

            if (acc, sym, THESIS_KEY) in existing_keys:
                continue  # already has a position record

            # Weighted-average entry price from plan records with valid prices.
            price_valid = [
                (float(r[1]), float(r[2] or 0))
                for r in tp_list
                if r[1] and float(r[1]) > 1.0
            ]
            if price_valid:
                total_w = sum(w for _, w in price_valid)
                if total_w > 0:
                    avg_entry_price = sum(p * w for p, w in price_valid) / total_w
                else:
                    avg_entry_price = sum(p for p, _ in price_valid) / len(price_valid)
            else:
                avg_entry_price = None

            opened_at = tp_list[0][3]  # created_at of earliest plan

            print(
                f"  [INJECT-FROM-PLAN] {acc}/{sym}  broker_qty={broker_qty:.4f}  "
                f"avg_entry={avg_entry_price}  (no intent records)"
            )
            positions_to_create.append(
                {
                    "acc": acc,
                    "sym": sym,
                    "status": PositionStatus.ACTIVE.value,
                    "direction": "LONG",
                    "total_qty": broker_qty,
                    "filled_qty": broker_qty,
                    "closed_qty": 0.0,
                    "open_qty": broker_qty,
                    "avg_entry_price": avg_entry_price,
                    "opened_at": opened_at,
                    "b_intents": [],  # no slices — data integrity over false history
                    "s_intents": [],
                    "_source": "trading_plan_fallback",
                }
            )

    if not positions_to_create:
        print("[Backfill] No net-positive open positions found (after filtering).")
        return

    print(f"\n[Backfill] Found {len(positions_to_create)} symbol(s) to backfill:")
    for p in positions_to_create:
        print(
            f"  {'[DRY]' if dry_run else '[CREATE]'} {p['acc']}/{p['sym']}  "
            f"status={p['status']}  open_qty={p['open_qty']:.4f}  "
            f"total_buy={p['total_qty']:.4f}  total_sell={p['closed_qty']:.4f}  "
            f"avg_entry={p['avg_entry_price']}  opened_at={p['opened_at']}"
        )

    if dry_run:
        print(
            f"\n[Backfill] Dry-run complete (nothing written).  "
            f"Re-run with --execute to apply."
        )
        return

    # ── 6. Write to DB ──────────────────────────────────────────────────────
    created_positions = 0
    created_slices = 0

    for p in positions_to_create:
        pos = Position(
            account_id=p["acc"],
            symbol=p["sym"],
            thesis_key=THESIS_KEY,
            status=p["status"],
            direction=p["direction"],
            total_qty=p["total_qty"],
            filled_qty=p["filled_qty"],
            closed_qty=p["closed_qty"],
            open_qty=p["open_qty"],
            avg_entry_price=p["avg_entry_price"],
            opened_at=p["opened_at"],
            last_action_at=(p["s_intents"] or p["b_intents"])[-1].created_at,
        )
        db.add(pos)
        await db.flush()  # get pos.id

        # BUY slices
        for intent in p["b_intents"]:
            slc = ExecutionSlice(
                position_id=pos.id,
                account_id=p["acc"],
                symbol=p["sym"],
                action=SliceAction.OPEN.value,
                status=SliceStatus.FILLED.value,
                requested_qty=intent.qty or 0.0,
                submitted_qty=intent.qty or 0.0,
                filled_qty=intent.qty or 0.0,
                signal_id=intent.signal_id,
                signal_db_id=intent.signal_db_id,
                intent_id=intent.intent_id,
                execution_path=ExecutionPath.AUTONOMOUS.value,
                order_ids=[intent.order_id] if intent.order_id else None,
            )
            db.add(slc)
            await db.flush()
            intent.position_id = pos.id
            intent.execution_slice_id = slc.id
            db.add(intent)
            created_slices += 1

        # SELL slices (partial close history)
        for intent in p["s_intents"]:
            slc = ExecutionSlice(
                position_id=pos.id,
                account_id=p["acc"],
                symbol=p["sym"],
                action=SliceAction.CLOSE.value,
                status=SliceStatus.FILLED.value,
                requested_qty=intent.qty or 0.0,
                submitted_qty=intent.qty or 0.0,
                filled_qty=intent.qty or 0.0,
                signal_id=intent.signal_id,
                signal_db_id=intent.signal_db_id,
                intent_id=intent.intent_id,
                execution_path=ExecutionPath.AUTONOMOUS.value,
                order_ids=[intent.order_id] if intent.order_id else None,
            )
            db.add(slc)
            await db.flush()
            intent.position_id = pos.id
            intent.execution_slice_id = slc.id
            db.add(intent)
            created_slices += 1

        created_positions += 1
        print(
            f"    → Position id={pos.id} {p['sym']} created  "
            f"({len(p['b_intents'])} open + {len(p['s_intents'])} close slices)"
        )

    await db.commit()
    print(
        f"\n[Backfill] Committed. "
        f"positions_created={created_positions}  "
        f"slices_created={created_slices}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill ACTIVE/PARTIALLY_CLOSED positions for US stocks "
            "that predate the V10.4.4 Position lifecycle feature."
        )
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
    parser.add_argument(
        "--min-qty",
        type=float,
        default=0.01,
        help=(
            "Minimum net open qty to consider a position still active "
            "(default: 0.01).  Use a higher value to skip near-zero residuals."
        ),
    )
    parser.add_argument(
        "--broker-positions",
        default=None,
        metavar="SYMBOL:QTY,...",
        help=(
            "Comma-separated list of actual broker holdings used for two-way "
            "reconciliation.  Format: AMD:2322,MSFT:100,QCOM:853  "
            "Symbols not listed are treated as having 0 broker qty."
        ),
    )
    args = parser.parse_args()

    broker_pos = _parse_broker_positions(args.broker_positions)

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionFactory() as db:
        await _backfill(
            db,
            dry_run=not args.execute,
            account_id_filter=args.account_id,
            min_qty=args.min_qty,
            broker_positions=broker_pos,
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
