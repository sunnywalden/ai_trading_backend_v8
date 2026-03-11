#!/usr/bin/env python3
"""repair_signal_integrity_v10_5_4.py

检查并修复 trading_signals 的 V10.5.4 信号完整性一致性：

  1. signal_origin_mode 与 canonical payload.origin_mode 不一致
  2. canonical payload 缺失或版本落后
  3. native signal_transitions 缺失

默认仅检查；传 --apply 后会直接修复。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import and_, desc, select

from app.models.db import SessionLocal, engine
from app.models.trading_signal import TradingSignal
from scripts.maintenance.backfill_signal_integrity_v10_5_4 import (
    _canonical_payload_missing_or_stale,
    _infer_origin_mode,
    _normalize_origin_mode,
    _transitions_missing,
)


@dataclass
class RepairStats:
    scanned: int = 0
    stale_origin_mode: int = 0
    stale_payload: int = 0
    missing_transitions: int = 0
    repaired: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair V10.5.4 signal integrity fields"
    )
    parser.add_argument("--check", action="store_true", help="只检查（默认）")
    parser.add_argument("--apply", action="store_true", help="真正写库")
    parser.add_argument(
        "--since-days",
        type=int,
        default=365,
        help="仅扫描最近 N 天的数据，默认 365",
    )
    parser.add_argument(
        "--account-id",
        type=str,
        default=None,
        help="仅处理指定 account_id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="最多扫描多少条记录，默认 5000",
    )
    return parser.parse_args()


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def run_repair(args: argparse.Namespace) -> RepairStats:
    from scripts.maintenance.backfill_signal_integrity_v10_5_4 import run_backfill

    stats = RepairStats()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(args.since_days, 1))

    async with SessionLocal() as session:
        conditions = [TradingSignal.created_at >= cutoff]
        if args.account_id:
            conditions.append(TradingSignal.account_id == args.account_id)

        stmt = (
            select(TradingSignal)
            .where(and_(*conditions))
            .order_by(desc(TradingSignal.created_at), desc(TradingSignal.id))
            .limit(max(args.limit, 1))
        )
        rows = list((await session.execute(stmt)).scalars().all())
        stats.scanned = len(rows)

        for signal in rows:
            meta = _safe_dict(signal.extra_metadata)
            expected_origin = _infer_origin_mode(signal)
            payload = _safe_dict(meta.get("signal_payload"))
            payload_origin = _normalize_origin_mode(payload.get("origin_mode"))
            current_origin = _normalize_origin_mode(signal.signal_origin_mode)

            if current_origin != expected_origin or payload_origin not in {
                None,
                expected_origin,
            }:
                stats.stale_origin_mode += 1
            if _canonical_payload_missing_or_stale(meta):
                stats.stale_payload += 1
            if _transitions_missing(meta):
                stats.missing_transitions += 1

        if args.apply:
            backfill_stats = await run_backfill(args)
            stats.repaired = backfill_stats.updated

    return stats


async def main_async(args: argparse.Namespace) -> None:
    stats = await run_repair(args)
    mode = "APPLY" if args.apply else "CHECK"
    print(f"[{mode}] scanned={stats.scanned}")
    print(f"[{mode}] stale_origin_mode={stats.stale_origin_mode}")
    print(f"[{mode}] stale_payload={stats.stale_payload}")
    print(f"[{mode}] missing_transitions={stats.missing_transitions}")
    print(f"[{mode}] repaired={stats.repaired}")
    if not args.apply:
        print("[CHECK] dry-run 完成；如需修复，请显式加 --apply")
    await engine.dispose()


def main() -> None:
    args = parse_args()
    if not args.check and not args.apply:
        args.check = True
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
