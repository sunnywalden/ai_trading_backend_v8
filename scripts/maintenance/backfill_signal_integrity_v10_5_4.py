#!/usr/bin/env python3
"""backfill_signal_integrity_v10_5_4.py

回补 trading_signals 的 V10.5.4 信号完整性字段：

  1. signal_origin_mode
  2. extra_metadata.signal_payload（canonical payload）
  3. extra_metadata.signal_transitions / latest_transition

默认 dry-run，仅检查不写库；必须显式加 --apply 才执行更新。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import and_, desc, select

from app.engine.signal_engine import SignalEngine
from app.models.db import SessionLocal, engine
from app.models.trading_signal import SignalOriginMode, TradingSignal
from app.services.signal_transition_service import signal_transition_service

VALID_ORIGIN_MODES = {mode.value for mode in SignalOriginMode}


@dataclass
class BackfillStats:
    scanned: int = 0
    eligible: int = 0
    updated: int = 0
    origin_mode_fixed: int = 0
    payload_rebuilt: int = 0
    transitions_rebuilt: int = 0
    already_complete: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill V10.5.4 signal integrity fields"
    )
    parser.add_argument("--check", action="store_true", help="只检查（默认）")
    parser.add_argument("--apply", action="store_true", help="真正写库")
    parser.add_argument(
        "--since-days",
        type=int,
        default=180,
        help="仅扫描最近 N 天的数据，默认 180",
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


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_origin_mode(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text if text in VALID_ORIGIN_MODES else None


def _contains_mock_dimensions(payload: dict[str, Any]) -> bool:
    for item in _safe_list(payload.get("dimensions")):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "")
        if "mock" in description.lower():
            return True
    return False


def _infer_origin_mode(signal: TradingSignal) -> str:
    if _normalize_origin_mode(signal.signal_origin_mode):
        return str(signal.signal_origin_mode).upper()

    extra = _safe_dict(signal.extra_metadata)
    factor = _safe_dict(signal.factor_scores)
    signal_dims = _safe_dict(factor.get("signal_dimensions"))
    signal_payload = _safe_dict(extra.get("signal_payload"))

    for candidate in (
        extra.get("signal_origin_mode"),
        signal_payload.get("origin_mode"),
        factor.get("signal_origin_mode"),
        signal_dims.get("signal_origin_mode"),
    ):
        normalized = _normalize_origin_mode(candidate)
        if normalized:
            return normalized

    notes = " ".join(
        filter(
            None,
            [
                str(signal.notes or ""),
                str(extra.get("watchtower_reason_detail") or ""),
                str(extra.get("resonance_metadata_source") or ""),
            ],
        )
    ).lower()
    if "backfill" in notes:
        return SignalOriginMode.BACKFILL.value

    if _contains_mock_dimensions(signal_dims) or _contains_mock_dimensions(extra):
        return SignalOriginMode.SYNTHETIC.value

    return SignalOriginMode.REAL.value


def _extract_signal_dimensions(signal: TradingSignal) -> dict[str, Any]:
    extra = _safe_dict(signal.extra_metadata)
    factor = _safe_dict(signal.factor_scores)
    signal_dims = _safe_dict(factor.get("signal_dimensions"))
    signal_payload = _safe_dict(extra.get("signal_payload"))
    payload_dims = _safe_dict(signal_payload.get("dimensions"))
    payload_quality = _safe_dict(signal_payload.get("quality_inputs"))

    merged: dict[str, Any] = {}
    for payload in (factor, signal_dims, extra, payload_dims, payload_quality):
        merged.update(_safe_dict(payload))
    return merged


def _build_strategy_context(signal: TradingSignal) -> Any:
    extra = _safe_dict(signal.extra_metadata)
    return SimpleNamespace(
        strategy_id=signal.strategy_id,
        id=signal.strategy_run_id,
        strategy=None,
        strategy_version=extra.get("strategy_version"),
        target_universe=extra.get("run_universe"),
    )


def _canonical_payload_missing_or_stale(meta: dict[str, Any]) -> bool:
    payload = _safe_dict(meta.get("signal_payload"))
    return (
        not payload
        or payload.get("version") != SignalEngine.CANONICAL_SIGNAL_PAYLOAD_VERSION
    )


def _transitions_missing(meta: dict[str, Any]) -> bool:
    return signal_transition_service.latest_transition(meta) is None


def _is_eligible(signal: TradingSignal) -> bool:
    meta = _safe_dict(signal.extra_metadata)
    if _normalize_origin_mode(signal.signal_origin_mode) is None:
        return True
    if _canonical_payload_missing_or_stale(meta):
        return True
    if _transitions_missing(meta):
        return True
    return False


async def run_backfill(args: argparse.Namespace) -> BackfillStats:
    stats = BackfillStats()
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
            if not _is_eligible(signal):
                stats.already_complete += 1
                continue

            stats.eligible += 1
            meta = _safe_dict(signal.extra_metadata).copy()
            dims = _extract_signal_dimensions(signal)
            origin_mode = _infer_origin_mode(signal)
            updated = False

            if _normalize_origin_mode(signal.signal_origin_mode) != origin_mode:
                if args.apply:
                    signal.signal_origin_mode = origin_mode
                meta["signal_origin_mode"] = origin_mode
                stats.origin_mode_fixed += 1
                updated = True

            if _canonical_payload_missing_or_stale(meta):
                payload = SignalEngine._build_canonical_signal_payload(
                    signal_dims={**dims, "signal_origin_mode": origin_mode},
                    signal_strength=float(signal.signal_strength or 0.0),
                    confidence=float(signal.confidence or 0.0),
                    direction=str(signal.direction or "LONG"),
                    signal_type=(
                        signal.signal_type.value if signal.signal_type else "ENTRY"
                    ),
                    quantity_mode=str(signal.quantity_mode or "PCT_EQUITY"),
                    quantity_value=float(signal.quantity_value or 0.0),
                    suggested_quantity=float(signal.suggested_quantity or 0.0),
                    strategy_run=_build_strategy_context(signal),
                )
                payload["source"] = (
                    signal.signal_source.value if signal.signal_source else "STRATEGY"
                )
                meta["signal_payload"] = payload
                stats.payload_rebuilt += 1
                updated = True

            if _transitions_missing(meta):
                meta = signal_transition_service.append_transition(
                    meta,
                    from_status=str(
                        signal.status.value if signal.status else "UNKNOWN"
                    ),
                    to_status=str(signal.status.value if signal.status else "UNKNOWN"),
                    actor="V1054_BACKFILL",
                    stage="SIGNAL_INTEGRITY_BACKFILL",
                    reason_code="BACKFILL_RECONCILE",
                    reason_detail="Rebuilt native transition history for legacy signal",
                )
                stats.transitions_rebuilt += 1
                updated = True

            if not updated:
                continue

            meta["signal_integrity_backfilled_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            meta["signal_integrity_backfill_source"] = "v10_5_4"
            if args.apply:
                signal.extra_metadata = meta
                stats.updated += 1

        if args.apply and stats.updated > 0:
            await session.commit()

    return stats


async def main_async(args: argparse.Namespace) -> None:
    stats = await run_backfill(args)
    mode = "APPLY" if args.apply else "CHECK"
    print(f"[{mode}] scanned={stats.scanned}")
    print(f"[{mode}] eligible={stats.eligible}")
    print(f"[{mode}] already_complete={stats.already_complete}")
    print(f"[{mode}] origin_mode_fixed={stats.origin_mode_fixed}")
    print(f"[{mode}] payload_rebuilt={stats.payload_rebuilt}")
    print(f"[{mode}] transitions_rebuilt={stats.transitions_rebuilt}")
    print(f"[{mode}] updated={stats.updated}")
    if not args.apply:
        print("[CHECK] dry-run 完成；如需写库，请显式加 --apply")
    await engine.dispose()


def main() -> None:
    args = parse_args()
    if not args.check and not args.apply:
        args.check = True
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
