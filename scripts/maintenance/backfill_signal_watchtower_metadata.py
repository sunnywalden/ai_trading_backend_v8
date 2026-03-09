#!/usr/bin/env python3
"""backfill_signal_watchtower_metadata.py

为生产环境回补 trading_signals.extra_metadata 中的 watchtower 统一字段。

默认仅检查（dry-run），不会写库；必须显式传 --apply 才执行更新。

用法：
  python scripts/maintenance/backfill_signal_watchtower_metadata.py --check
  python scripts/maintenance/backfill_signal_watchtower_metadata.py --apply
    python scripts/maintenance/backfill_signal_watchtower_metadata.py \
        --apply --since-days 14
    python scripts/maintenance/backfill_signal_watchtower_metadata.py \
        --apply --account-id 20190130122050760

回补策略（仅针对缺失 watchtower_stage 的记录）：
  - VALIDATED + risk_check_passed=YES
      => SIGNAL_VALIDATION / PASSED
  - REJECTED + risk_check_passed=NO
      => SIGNAL_VALIDATION / REJECTED
         * Trading mode is OFF => TRADING_MODE_OFF
         * 其他 => SIGNAL_VALIDATION_BLOCKED
  - REJECTED + risk_check_passed=YES
      => QUALITY_FUNNEL / REJECTED
         * 默认原因码：QUALITY_FUNNEL_PRE_INTENT_REJECTED

注意：
  1. 该脚本不会覆盖已有 watchtower_stage。
  2. 该脚本不会直接回补 signal_quality_audit_logs，仅修复 trading_signals 元数据。
  3. 建议先 --check，再按小窗口/单账号执行 --apply。
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

from sqlalchemy import and_, select

from app.models.db import SessionLocal, engine
from app.models.trading_signal import SignalStatus, TradingSignal


@dataclass
class BackfillStats:
    scanned: int = 0
    eligible: int = 0
    updated: int = 0
    skipped_existing: int = 0
    unknown: int = 0
    validation_passed: int = 0
    validation_rejected: int = 0
    quality_funnel_rejected: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill watchtower metadata on trading_signals"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查将会更新多少记录（默认行为）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行回补更新",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="仅扫描最近 N 天的数据，默认 30",
    )
    parser.add_argument(
        "--account-id",
        type=str,
        default=None,
        help="只回补指定 account_id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="单次最多处理多少条候选记录，默认 5000",
    )
    return parser.parse_args()


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _derive_backfill_payload(signal: TradingSignal) -> dict[str, Any] | None:
    meta = _safe_dict(signal.extra_metadata)
    if meta.get("watchtower_stage"):
        return None

    risk_details = _safe_dict(signal.risk_check_details)
    status = signal.status.value if getattr(signal, "status", None) else ""
    now_iso = datetime.now(timezone.utc).isoformat()

    regime = meta.get("watchtower_regime") or meta.get("regime")

    if (
        status == SignalStatus.VALIDATED.value
        and signal.risk_check_passed == "YES"
    ):
        return {
            "watchtower_stage": "SIGNAL_VALIDATION",
            "watchtower_result": "PASSED",
            "watchtower_reason_code": None,
            "watchtower_reason_detail": None,
            "watchtower_reason_category": "VALIDATION",
            "watchtower_rejected_at_layer": None,
            "watchtower_updated_at": now_iso,
            "watchtower_regime": regime,
        }

    if (
        status == SignalStatus.REJECTED.value
        and signal.risk_check_passed == "NO"
    ):
        detail = str(risk_details.get("reason") or "Signal validation blocked")
        reason_code = (
            "TRADING_MODE_OFF"
            if detail == "Trading mode is OFF"
            else "SIGNAL_VALIDATION_BLOCKED"
        )
        return {
            "watchtower_stage": "SIGNAL_VALIDATION",
            "watchtower_result": "REJECTED",
            "watchtower_reason_code": reason_code,
            "watchtower_reason_detail": detail,
            "watchtower_reason_category": "VALIDATION",
            "watchtower_rejected_at_layer": None,
            "watchtower_updated_at": now_iso,
            "watchtower_regime": regime,
        }

    if (
        status == SignalStatus.REJECTED.value
        and signal.risk_check_passed == "YES"
    ):
        return {
            "watchtower_stage": "QUALITY_FUNNEL",
            "watchtower_result": "REJECTED",
            "watchtower_reason_code": "QUALITY_FUNNEL_PRE_INTENT_REJECTED",
            "watchtower_reason_detail": (
                "Legacy signal was rejected after validation before "
                "execution intent was created"
            ),
            "watchtower_reason_category": "QUALITY_FUNNEL",
            "watchtower_rejected_at_layer": meta.get(
                "funnel_rejected_at_layer"
            ),
            "watchtower_updated_at": now_iso,
            "watchtower_regime": regime,
        }

    return {}


async def run_backfill(args: argparse.Namespace) -> BackfillStats:
    stats = BackfillStats()
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=max(args.since_days, 1)
    )

    async with SessionLocal() as session:
        conditions = [TradingSignal.created_at >= cutoff]
        if args.account_id:
            conditions.append(TradingSignal.account_id == args.account_id)

        stmt = (
            select(TradingSignal)
            .where(and_(*conditions))
            .order_by(TradingSignal.created_at.desc(), TradingSignal.id.desc())
            .limit(max(args.limit, 1))
        )
        rows = (await session.execute(stmt)).scalars().all()
        stats.scanned = len(rows)

        for signal in rows:
            payload = _derive_backfill_payload(signal)
            if payload is None:
                stats.skipped_existing += 1
                continue

            if payload == {}:
                stats.unknown += 1
                continue

            stats.eligible += 1
            if payload["watchtower_stage"] == "SIGNAL_VALIDATION":
                if payload["watchtower_result"] == "PASSED":
                    stats.validation_passed += 1
                else:
                    stats.validation_rejected += 1
            elif payload["watchtower_stage"] == "QUALITY_FUNNEL":
                stats.quality_funnel_rejected += 1

            if not args.apply:
                continue

            meta = _safe_dict(signal.extra_metadata).copy()
            for key, value in payload.items():
                if value is None and key not in meta:
                    meta[key] = None
                elif value is not None:
                    meta[key] = value
            signal.extra_metadata = meta
            stats.updated += 1

        if args.apply and stats.updated > 0:
            await session.commit()

    return stats


async def run_check(args: argparse.Namespace) -> None:
    stats = await run_backfill(args)
    mode = "APPLY" if args.apply else "CHECK"
    print(f"[{mode}] scanned={stats.scanned}")
    print(f"[{mode}] skipped_existing={stats.skipped_existing}")
    print(f"[{mode}] eligible={stats.eligible}")
    print(f"[{mode}] unknown={stats.unknown}")
    print(f"[{mode}] validation_passed={stats.validation_passed}")
    print(f"[{mode}] validation_rejected={stats.validation_rejected}")
    print(f"[{mode}] quality_funnel_rejected={stats.quality_funnel_rejected}")
    print(f"[{mode}] updated={stats.updated}")

    if not args.apply:
        print("[CHECK] dry-run 完成；如需写库，请显式加 --apply")


async def run_verify(args: argparse.Namespace) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=max(args.since_days, 1)
    )
    async with SessionLocal() as session:
        conditions = [TradingSignal.created_at >= cutoff]
        if args.account_id:
            conditions.append(TradingSignal.account_id == args.account_id)

        stmt = select(TradingSignal.extra_metadata).where(and_(*conditions))
        rows = (await session.execute(stmt)).all()
        total = len(rows)
        missing_stage = 0
        for row in rows:
            meta = _safe_dict(row[0])
            if not meta.get("watchtower_stage"):
                missing_stage += 1
        print(
            "[VERIFY] total=%s missing_watchtower_stage=%s"
            % (total, missing_stage)
        )


async def main_async(args: argparse.Namespace) -> None:
    try:
        await run_check(args)
        if args.apply:
            await run_verify(args)
    finally:
        await engine.dispose()


def main() -> None:
    args = parse_args()
    if not args.check and not args.apply:
        args.check = True
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
