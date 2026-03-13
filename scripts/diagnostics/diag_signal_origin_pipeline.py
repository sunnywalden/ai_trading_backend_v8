#!/usr/bin/env python3
"""diag_signal_origin_pipeline.py — 排查最近窗口内信号来源与控制面分布。

用途：
1. 统计最近 N 小时 REAL / SYNTHETIC / BACKFILL 信号分布；
2. 观察 GENERATED/VALIDATED/QUEUED/EXECUTED 等状态的来源结构；
3. 汇总 Watchtower / Validation / Execution Intent 的阻塞原因；
4. 快速定位“有信号但零成交”到底卡在发现、验证还是执行层。

示例：
  python scripts/diagnostics/diag_signal_origin_pipeline.py
  python scripts/diagnostics/diag_signal_origin_pipeline.py --account-id 21272246230273657
  python scripts/diagnostics/diag_signal_origin_pipeline.py --since-hours 48 --limit 800 --sample-limit 15
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import app.models.strategy  # noqa: F401
from sqlalchemy import and_, desc, select

from app.models.db import SessionLocal, engine
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.trading_signal import SignalStatus, TradingSignal
from app.services.signal_transition_service import signal_transition_service

PENDING_STATUSES = {
    SignalStatus.GENERATED.value,
    SignalStatus.VALIDATED.value,
    SignalStatus.QUEUED.value,
    SignalStatus.EXECUTING.value,
}


@dataclass
class SignalSnapshot:
    signal_id: str
    db_id: int
    symbol: str
    account_id: str
    origin_mode: str
    status: str
    signal_type: str
    created_at: datetime | None
    order_id: str | None
    watchtower_reason_code: str | None
    validation_reason: str | None
    latest_transition: dict[str, Any] | None
    intent_status: str | None
    intent_reason: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="诊断信号来源与执行控制面分布")
    parser.add_argument("--account-id", type=str, default=None, help="仅查看指定 account_id")
    parser.add_argument("--since-hours", type=int, default=24, help="仅统计最近 N 小时，默认 24")
    parser.add_argument("--limit", type=int, default=500, help="最多扫描多少条 signal，默认 500")
    parser.add_argument("--sample-limit", type=int, default=12, help="最多打印多少条样本，默认 12")
    parser.add_argument("--only-pending", action="store_true", help="仅查看 pending 状态（GENERATED/VALIDATED/QUEUED/EXECUTING）")
    return parser.parse_args()


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_origin(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"REAL", "SYNTHETIC", "BACKFILL"}:
        return text
    return "UNKNOWN"


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _extract_block_reason(signal: TradingSignal) -> tuple[str | None, str | None, dict[str, Any] | None]:
    meta = _safe_dict(signal.extra_metadata)
    risk = _safe_dict(signal.risk_check_details)
    latest_transition = signal_transition_service.latest_transition(meta)
    return (
        meta.get("watchtower_reason_code") or meta.get("watchtower_reason_detail"),
        risk.get("reason") or (latest_transition or {}).get("reason_code") or (latest_transition or {}).get("reason_detail"),
        latest_transition,
    )


async def _load_signals(args: argparse.Namespace) -> list[SignalSnapshot]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, args.since_hours))
    async with SessionLocal() as session:
        conditions = [TradingSignal.created_at >= cutoff]
        if args.account_id:
            conditions.append(TradingSignal.account_id == args.account_id)
        if args.only_pending:
            conditions.append(TradingSignal.status.in_(list(PENDING_STATUSES)))

        stmt = (
            select(TradingSignal)
            .where(and_(*conditions))
            .order_by(desc(TradingSignal.created_at), desc(TradingSignal.id))
            .limit(max(1, args.limit))
        )
        rows = list((await session.execute(stmt)).scalars().all())

        signal_ids = [row.signal_id for row in rows if row.signal_id]
        intent_map: dict[str, AutonomousExecutionIntent] = {}
        if signal_ids:
            intent_stmt = (
                select(AutonomousExecutionIntent)
                .where(AutonomousExecutionIntent.signal_id.in_(signal_ids))
                .order_by(desc(AutonomousExecutionIntent.created_at), desc(AutonomousExecutionIntent.id))
            )
            intents = list((await session.execute(intent_stmt)).scalars().all())
            for intent in intents:
                intent_map.setdefault(intent.signal_id, intent)

        snapshots: list[SignalSnapshot] = []
        for row in rows:
            meta = _safe_dict(row.extra_metadata)
            signal_payload = _safe_dict(meta.get("signal_payload"))
            watchtower_reason, validation_reason, latest_transition = _extract_block_reason(row)
            intent = intent_map.get(row.signal_id)
            snapshots.append(
                SignalSnapshot(
                    signal_id=row.signal_id,
                    db_id=row.id,
                    symbol=row.symbol,
                    account_id=row.account_id,
                    origin_mode=_normalize_origin(
                        row.signal_origin_mode
                        or signal_payload.get("origin_mode")
                        or meta.get("signal_origin_mode")
                    ),
                    status=row.status.value if getattr(row.status, "value", None) else str(row.status),
                    signal_type=row.signal_type.value if getattr(row.signal_type, "value", None) else str(row.signal_type),
                    created_at=row.created_at,
                    order_id=row.order_id,
                    watchtower_reason_code=str(watchtower_reason) if watchtower_reason else None,
                    validation_reason=str(validation_reason) if validation_reason else None,
                    latest_transition=latest_transition,
                    intent_status=getattr(intent, "status", None),
                    intent_reason=getattr(intent, "reason", None),
                )
            )
        return snapshots


def _print_counter(title: str, counter: Counter[str], *, top: int | None = None) -> None:
    print(f"\n## {title}")
    if not counter:
        print("  (none)")
        return
    items = counter.most_common(top)
    for key, count in items:
        print(f"  {key}: {count}")


def _sample_sort_key(item: SignalSnapshot) -> tuple[datetime, int]:
    dt = item.created_at or datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt, item.db_id


def _print_samples(rows: list[SignalSnapshot], sample_limit: int) -> None:
    if not rows:
        return
    print("\n## 样本信号")
    ordered = sorted(rows, key=_sample_sort_key, reverse=True)[:sample_limit]
    for row in ordered:
        latest = row.latest_transition or {}
        latest_desc = latest.get("to_status") or latest.get("reason_code") or "-"
        print(
            f"  [{_fmt_dt(row.created_at)}] {row.symbol:<8} origin={row.origin_mode:<9} "
            f"status={row.status:<10} type={row.signal_type:<6} order_id={row.order_id or '-'}"
        )
        print(
            f"    signal_id={row.signal_id} intent={row.intent_status or '-'} "
            f"watchtower={row.watchtower_reason_code or '-'} validation={row.validation_reason or '-'} latest={latest_desc}"
        )
        if row.intent_reason:
            print(f"    intent_reason={row.intent_reason}")


def render_report(rows: list[SignalSnapshot], *, sample_limit: int) -> None:
    total = len(rows)
    print("=" * 72)
    print("Signal Origin Pipeline Diagnostic")
    print("=" * 72)
    print(f"scanned_signals={total}")
    if total == 0:
        print("没有匹配的信号记录。")
        return

    by_origin = Counter(row.origin_mode for row in rows)
    by_status = Counter(row.status for row in rows)
    origin_status = Counter(f"{row.origin_mode}/{row.status}" for row in rows)
    pending_origin = Counter(
        row.origin_mode for row in rows if row.status in PENDING_STATUSES
    )
    executed_origin = Counter(
        row.origin_mode for row in rows if row.status == SignalStatus.EXECUTED.value
    )
    intent_status = Counter(row.intent_status or "NO_INTENT" for row in rows)
    watchtower_reasons = Counter(row.watchtower_reason_code or "NONE" for row in rows if row.watchtower_reason_code)
    validation_reasons = Counter(row.validation_reason or "NONE" for row in rows if row.validation_reason)
    intent_reasons = Counter(row.intent_reason or "NONE" for row in rows if row.intent_reason)

    synthetic_pending = [row for row in rows if row.origin_mode == "SYNTHETIC" and row.status in PENDING_STATUSES]
    real_pending = [row for row in rows if row.origin_mode == "REAL" and row.status in PENDING_STATUSES]
    synthetic_executed = [row for row in rows if row.origin_mode == "SYNTHETIC" and row.status == SignalStatus.EXECUTED.value]

    _print_counter("来源分布", by_origin)
    _print_counter("状态分布", by_status)
    _print_counter("来源 / 状态交叉", origin_status, top=20)
    _print_counter("Pending 来源分布", pending_origin)
    _print_counter("Executed 来源分布", executed_origin)
    _print_counter("Execution Intent 状态分布", intent_status)
    _print_counter("Watchtower 原因", watchtower_reasons, top=10)
    _print_counter("Validation / Transition 原因", validation_reasons, top=10)
    _print_counter("Execution Intent 原因", intent_reasons, top=10)

    print("\n## 关键结论")
    print(f"  REAL pending: {len(real_pending)}")
    print(f"  SYNTHETIC pending: {len(synthetic_pending)}")
    print(f"  SYNTHETIC executed: {len(synthetic_executed)}")
    if synthetic_pending and not real_pending:
        print("  ⚠️ 当前窗口内 pending 主要是 SYNTHETIC，自动执行主链大概率会继续跳过。")
    if real_pending:
        print("  ✅ 当前窗口内存在 REAL pending，可继续检查 RiskGate / Intent / Broker 层。")
    if synthetic_executed:
        print("  ⚠️ 发现 SYNTHETIC 已执行记录，请核查是否有非预期执行路径。")

    blocked_by_origin: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.status in {SignalStatus.REJECTED.value, SignalStatus.SKIPPED.value, SignalStatus.FAILED.value}:
            reason = row.intent_reason or row.watchtower_reason_code or row.validation_reason or "UNKNOWN"
            blocked_by_origin[row.origin_mode][reason] += 1

    for origin, counter in sorted(blocked_by_origin.items()):
        _print_counter(f"{origin} 阻塞原因", counter, top=8)

    _print_samples(rows, sample_limit)


async def main_async(args: argparse.Namespace) -> None:
    rows = await _load_signals(args)
    render_report(rows, sample_limit=max(1, args.sample_limit))
    await engine.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
