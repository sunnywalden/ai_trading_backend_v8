#!/usr/bin/env python3
"""cleanup_synthetic_pending_signals.py — 安全清理旧的 synthetic pending 信号。

默认 dry-run，只会扫描：
- signal_origin_mode = SYNTHETIC
- status in GENERATED / VALIDATED
- 创建时间早于 --older-than-hours

可选通过 --include-queued 把 오래 QUEUED synthetic 一并过期；
不会触碰 REAL / BACKFILL，也不会默认触碰 EXECUTING / EXECUTED。
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import app.models.strategy  # noqa: F401
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import SessionLocal, engine
from app.models.trading_signal import SignalStatus, TradingSignal
from app.services.signal_transition_service import signal_transition_service

DEFAULT_STATUSES = {SignalStatus.GENERATED, SignalStatus.VALIDATED}


@dataclass
class CleanupStats:
    scanned: int = 0
    matched: int = 0
    expired: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="过期旧的 synthetic pending 信号（默认 dry-run）")
    parser.add_argument("--account-id", type=str, default=None, help="仅处理指定 account_id")
    parser.add_argument("--older-than-hours", type=int, default=6, help="仅处理早于 N 小时的记录，默认 6")
    parser.add_argument("--limit", type=int, default=500, help="最多扫描多少条 signal，默认 500")
    parser.add_argument("--sample-limit", type=int, default=20, help="最多打印多少条样本，默认 20")
    parser.add_argument("--include-queued", action="store_true", help="额外纳入 오래 QUEUED synthetic 信号")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认仅 dry-run")
    return parser


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _matches_synthetic_pending(signal: TradingSignal, *, include_queued: bool) -> bool:
    status_set = set(DEFAULT_STATUSES)
    if include_queued:
        status_set.add(SignalStatus.QUEUED)
    if signal.status not in status_set:
        return False

    meta = _safe_dict(signal.extra_metadata)
    payload = _safe_dict(meta.get("signal_payload"))
    origin = str(
        signal.signal_origin_mode
        or payload.get("origin_mode")
        or meta.get("signal_origin_mode")
        or ""
    ).upper()
    return origin == "SYNTHETIC"


def _append_cleanup_metadata(signal: TradingSignal, *, reason: str, cleanup_at: datetime) -> None:
    meta = _safe_dict(signal.extra_metadata).copy()
    updated_meta = signal_transition_service.append_transition(
        meta,
        from_status=signal.status.value,
        to_status=SignalStatus.EXPIRED.value,
        actor="MAINTENANCE_SCRIPT",
        stage="MANUAL_CLEANUP",
        reason_code="SYNTHETIC_PENDING_CLEANUP",
        reason_detail=reason,
    )
    cleanup_payload = _safe_dict(updated_meta.get("cleanup"))
    if not isinstance(cleanup_payload, dict):
        cleanup_payload = {}
    cleanup_payload.update(
        {
            "synthetic_pending_cleanup": True,
            "cleanup_reason": reason,
            "cleanup_at": cleanup_at.isoformat(),
        }
    )
    updated_meta["cleanup"] = cleanup_payload
    signal.extra_metadata = updated_meta


async def load_candidates(session: AsyncSession, args: argparse.Namespace) -> tuple[list[TradingSignal], int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, args.older_than_hours))
    stmt = select(TradingSignal).order_by(desc(TradingSignal.created_at), desc(TradingSignal.id)).limit(max(1, args.limit))
    conditions = [TradingSignal.created_at <= cutoff]
    if args.account_id:
        conditions.append(TradingSignal.account_id == args.account_id)
    stmt = stmt.where(and_(*conditions))
    rows = list((await session.execute(stmt)).scalars().all())
    return [row for row in rows if _matches_synthetic_pending(row, include_queued=args.include_queued)], len(rows)


def print_candidates(rows: list[TradingSignal], *, sample_limit: int) -> None:
    print(f"matched={len(rows)}")
    if not rows:
        return
    status_counter = Counter(row.status.value for row in rows)
    print("status_breakdown=")
    for key, value in status_counter.most_common():
        print(f"  {key}: {value}")
    print("samples=")
    for row in rows[:sample_limit]:
        print(
            f"  [{_fmt_dt(row.created_at)}] db_id={row.id} signal_id={row.signal_id} "
            f"symbol={row.symbol} status={row.status.value} account={row.account_id}"
        )


async def run_cleanup(args: argparse.Namespace) -> CleanupStats:
    stats = CleanupStats()
    async with SessionLocal() as session:
        candidates, scanned = await load_candidates(session, args)
        stats.matched = len(candidates)
        stats.scanned = scanned

        print("=" * 72)
        print("Synthetic Pending Cleanup")
        print("=" * 72)
        print(f"mode={'APPLY' if args.apply else 'DRY_RUN'}")
        print(f"scanned={stats.scanned}")
        print(f"account_id={args.account_id or 'ALL'} older_than_hours={args.older_than_hours} include_queued={args.include_queued}")
        print_candidates(candidates, sample_limit=max(1, args.sample_limit))

        if not args.apply:
            print("\nDRY_RUN 完成；如需真正过期这些 synthetic pending，请加 --apply。")
            return stats

        now = datetime.now(timezone.utc)
        for signal in candidates:
            previous_status = signal.status.value
            signal.status = SignalStatus.EXPIRED
            signal.expired_at = now
            reason = f"manual synthetic pending cleanup from {previous_status}"
            _append_cleanup_metadata(signal, reason=reason, cleanup_at=now)
            note = signal.notes or ""
            signal.notes = f"{note} | {reason}".strip(" |")
            stats.expired += 1

        await session.commit()
        print(f"\n✅ 已过期 {stats.expired} 条旧 synthetic pending 信号。")
        return stats


async def main_async(args: argparse.Namespace) -> None:
    await run_cleanup(args)
    await engine.dispose()


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
