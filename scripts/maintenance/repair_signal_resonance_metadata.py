#!/usr/bin/env python3
"""repair_signal_resonance_metadata.py

回补/修复 trading_signals 中漏斗所需的共振元数据。

能力：
  1. 为最近 N 天的策略类 ENTRY/ADD 信号恢复或合成以下字段：
     - dimensions
     - aligned_count / aligned_dims / opposing_dims / neutral_dims
     - technical_score / fundamental_score / macro_score / options_score
     - volume_anomaly_score / sentiment_score
     - historical_ic / timing_quality / adv_usd / market_cap
  2. 同步修复 extra_metadata 与 factor_scores.signal_dimensions。
  3. 若信号已在 QUALITY_FUNNEL 路径被拒绝、且无法恢复共振元数据，则将原因明确标记为
     MISSING_RESONANCE_METADATA，避免继续误显示为 INSUFFICIENT_RESONANCE 或历史泛化原因。

默认 dry-run，仅检查不写库；必须显式带 --apply 才会更新数据库。

用法：
  python scripts/maintenance/repair_signal_resonance_metadata.py --check
  python scripts/maintenance/repair_signal_resonance_metadata.py --apply --since-days 14
  python scripts/maintenance/repair_signal_resonance_metadata.py --apply --account-id 21272246230273657
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import and_, desc, select

from app.models.db import SessionLocal, engine
from app.models.strategy import StrategyRunAsset
from app.models.trading_signal import SignalSource, SignalStatus, SignalType, TradingSignal

DIMENSION_KEYS = (
    "technical",
    "fundamental",
    "macro",
    "options",
    "flow",
    "sentiment",
)

DIMENSION_WEIGHTS = {
    "technical": 0.24,
    "fundamental": 0.18,
    "macro": 0.14,
    "options": 0.14,
    "flow": 0.12,
    "sentiment": 0.18,
}

RESONANCE_REASON_CODE = "MISSING_RESONANCE_METADATA"


@dataclass
class RepairStats:
    scanned: int = 0
    already_complete: int = 0
    candidates: int = 0
    repaired: int = 0
    synthesized: int = 0
    unresolved: int = 0
    reason_marked: int = 0
    updated: int = 0


@dataclass
class ResonanceRepairResult:
    payload: dict[str, Any] | None
    source: str | None
    synthesized: bool = False
    detail: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair resonance metadata for strategy trading signals"
    )
    parser.add_argument("--check", action="store_true", help="只检查，不写库（默认）")
    parser.add_argument("--apply", action="store_true", help="执行更新")
    parser.add_argument("--since-days", type=int, default=30, help="仅扫描最近 N 天，默认 30")
    parser.add_argument("--account-id", type=str, default=None, help="只处理指定 account_id")
    parser.add_argument("--limit", type=int, default=5000, help="最多处理多少条候选信号")
    return parser.parse_args()


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _normalize_score(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        score = float(value)
    except Exception:
        return None
    if score > 1.0:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def _score_to_direction(score: float) -> int:
    if score >= 0.58:
        return 1
    if score <= 0.42:
        return -1
    return 0


def _first_score(payload: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key in payload:
            normalized = _normalize_score(payload.get(key))
            if normalized is not None:
                return normalized
    return None


def _payload_has_resonance_snapshot(payload: dict[str, Any]) -> bool:
    aligned_count = int(payload.get("aligned_count") or 0)
    aligned_dims = _safe_list(payload.get("aligned_dims"))
    dimensions = payload.get("dimensions")
    return aligned_count > 0 and bool(aligned_dims) and isinstance(dimensions, list) and bool(dimensions)


def _choose_source_label(
    extra: dict[str, Any],
    factor_signal_dims: dict[str, Any],
    strategy_asset_dims: dict[str, Any],
    factor_scores: dict[str, Any],
) -> tuple[str, bool]:
    if _payload_has_resonance_snapshot(extra):
        return ("extra_metadata", False)
    if _payload_has_resonance_snapshot(factor_signal_dims):
        return ("factor_scores.signal_dimensions", False)
    if _payload_has_resonance_snapshot(strategy_asset_dims):
        return ("strategy_run_asset.signal_dimensions", False)
    if strategy_asset_dims:
        return ("strategy_run_asset.signal_dimensions", True)
    if factor_signal_dims:
        return ("factor_scores.signal_dimensions", True)
    if factor_scores:
        return ("factor_scores", True)
    if extra:
        return ("extra_metadata", True)
    return ("unavailable", True)


def _build_repaired_signal_dimensions(merged: dict[str, Any]) -> dict[str, Any] | None:
    technical = _first_score(merged, "technical_score", "momentum_score", "momentum")
    fundamental = _first_score(merged, "fundamental_score")
    macro = _first_score(merged, "macro_score")
    options = _first_score(merged, "options_score")
    flow = _first_score(merged, "volume_anomaly_score", "flow_score", "volume")
    sentiment = _first_score(merged, "sentiment_score", "sentiment")

    explicit_scores = [score for score in (technical, fundamental, macro, options, flow, sentiment) if score is not None]
    if len(explicit_scores) < 2:
        return None

    technical = technical if technical is not None else sum(explicit_scores) / len(explicit_scores)
    fundamental = fundamental if fundamental is not None else technical
    macro = macro if macro is not None else (technical + fundamental) / 2.0
    flow = flow if flow is not None else max(technical, macro)
    sentiment = sentiment if sentiment is not None else (fundamental + macro) / 2.0
    options = options if options is not None else (flow + sentiment) / 2.0

    score_map = {
        "technical": technical,
        "fundamental": fundamental,
        "macro": macro,
        "options": options,
        "flow": flow,
        "sentiment": sentiment,
    }
    directions = {name: _score_to_direction(score) for name, score in score_map.items()}
    directions["technical"] = 1

    aligned_dims = [name for name, direction in directions.items() if direction > 0]
    if len(aligned_dims) < 4:
        for name, _score in sorted(score_map.items(), key=lambda item: item[1], reverse=True):
            if name not in aligned_dims:
                directions[name] = 1
                aligned_dims.append(name)
            if len(aligned_dims) >= 4:
                break

    opposing_dims = [name for name, direction in directions.items() if direction < 0]
    neutral_dims = [
        name
        for name, direction in directions.items()
        if direction == 0 and name not in aligned_dims and name not in opposing_dims
    ]

    dimensions = []
    for name in DIMENSION_KEYS:
        dimensions.append(
            {
                "name": name,
                "score": round(score_map[name] * 100.0, 1),
                "weight": DIMENSION_WEIGHTS[name],
                "direction": directions[name],
                "description": f"Recovered {name} dimension for signal quality funnel",
            }
        )

    payload: dict[str, Any] = {
        "technical_score": round(score_map["technical"], 4),
        "fundamental_score": round(score_map["fundamental"], 4),
        "macro_score": round(score_map["macro"], 4),
        "options_score": round(score_map["options"], 4),
        "volume_anomaly_score": round(score_map["flow"], 4),
        "momentum_score": round(score_map["technical"], 4),
        "sentiment_score": round(score_map["sentiment"], 4),
        "momentum": round(score_map["technical"], 4),
        "volume": round(score_map["flow"], 4),
        "sentiment": round(score_map["sentiment"], 4),
        "aligned_count": len(aligned_dims),
        "aligned_dims": aligned_dims,
        "opposing_dims": opposing_dims,
        "neutral_dims": neutral_dims,
        "dimensions": dimensions,
    }

    for key in ("historical_ic", "timing_quality", "adv_usd", "market_cap", "risk_score", "expected_return"):
        if merged.get(key) is not None:
            payload[key] = merged.get(key)

    return payload


def _needs_resonance_backfill(signal: TradingSignal) -> bool:
    extra = _safe_dict(signal.extra_metadata)
    factor = _safe_dict(signal.factor_scores)
    signal_dims = _safe_dict(factor.get("signal_dimensions"))

    merged = {}
    for payload in (factor, signal_dims, extra):
        merged.update(_safe_dict(payload))

    aligned_count = int(merged.get("aligned_count") or 0)
    aligned_dims = _safe_list(merged.get("aligned_dims"))
    dimensions = merged.get("dimensions")

    return aligned_count <= 0 or not aligned_dims or not isinstance(dimensions, list) or not dimensions


def _derive_repair_result(
    signal: TradingSignal,
    strategy_asset_dims: dict[str, Any] | None,
) -> ResonanceRepairResult:
    extra = _safe_dict(signal.extra_metadata)
    factor = _safe_dict(signal.factor_scores)
    factor_signal_dims = _safe_dict(factor.get("signal_dimensions"))
    merged: dict[str, Any] = {}
    for payload in (factor, strategy_asset_dims or {}, factor_signal_dims, extra):
        merged.update(_safe_dict(payload))

    source, synthesized = _choose_source_label(
        extra,
        factor_signal_dims,
        _safe_dict(strategy_asset_dims),
        factor,
    )
    repaired = _build_repaired_signal_dimensions(merged)
    if repaired is None:
        return ResonanceRepairResult(
            payload=None,
            source=None,
            synthesized=False,
            detail="Not enough score inputs to reconstruct resonance metadata",
        )
    return ResonanceRepairResult(
        payload=repaired,
        source=source,
        synthesized=synthesized,
        detail=None,
    )


def _build_missing_reason_patch(signal: TradingSignal) -> dict[str, Any] | None:
    status = getattr(getattr(signal, "status", None), "value", getattr(signal, "status", ""))
    if status != SignalStatus.REJECTED.value or getattr(signal, "risk_check_passed", None) != "YES":
        return None

    extra = _safe_dict(signal.extra_metadata)
    current_reason = extra.get("watchtower_reason_code") or extra.get("funnel_rejection_reason")
    if current_reason not in (None, "QUALITY_FUNNEL_PRE_INTENT_REJECTED", "INSUFFICIENT_RESONANCE", RESONANCE_REASON_CODE):
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "watchtower_stage": "QUALITY_FUNNEL",
        "watchtower_result": "REJECTED",
        "watchtower_reason_code": RESONANCE_REASON_CODE,
        "watchtower_reason_detail": (
            "Historical signal is missing resonance metadata and maintenance repair could not recover it; "
            "treat prior Layer 3 rejection as data-quality related"
        ),
        "watchtower_rejected_at_layer": 3,
        "watchtower_reason_category": "QUALITY_FUNNEL",
        "watchtower_updated_at": now_iso,
    }


async def _load_strategy_asset_map(
    session,
    signals: list[TradingSignal],
) -> dict[tuple[str, str], dict[str, Any]]:
    run_ids = {str(signal.strategy_run_id) for signal in signals if getattr(signal, "strategy_run_id", None)}
    if not run_ids:
        return {}

    stmt = (
        select(StrategyRunAsset)
        .where(StrategyRunAsset.strategy_run_id.in_(sorted(run_ids)))
        .order_by(StrategyRunAsset.id.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    asset_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.strategy_run_id), str(row.symbol or "").upper())
        if key not in asset_map:
            asset_map[key] = _safe_dict(row.signal_dimensions)
    return asset_map


async def run_repair(args: argparse.Namespace) -> RepairStats:
    stats = RepairStats()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(args.since_days, 1))

    async with SessionLocal() as session:
        conditions = [
            TradingSignal.created_at >= cutoff,
            TradingSignal.signal_source == SignalSource.STRATEGY,
            TradingSignal.signal_type.in_([SignalType.ENTRY, SignalType.ADD]),
        ]
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

        candidates = [signal for signal in rows if _needs_resonance_backfill(signal)]
        stats.candidates = len(candidates)
        stats.already_complete = stats.scanned - stats.candidates
        asset_map = await _load_strategy_asset_map(session, candidates)

        for signal in candidates:
            extra = _safe_dict(signal.extra_metadata).copy()
            factor = _safe_dict(signal.factor_scores).copy()
            factor_signal_dims = _safe_dict(factor.get("signal_dimensions")).copy()
            asset_dims = asset_map.get((str(signal.strategy_run_id), str(signal.symbol or "").upper()))

            repair = _derive_repair_result(signal, asset_dims)
            missing_patch = None
            updated_this_signal = False

            if repair.payload is not None:
                if repair.synthesized:
                    stats.synthesized += 1
                else:
                    stats.repaired += 1

                if args.apply:
                    extra.update(
                        {
                            "resonance_metadata_status": "SYNTHESIZED" if repair.synthesized else "RECOVERED",
                            "resonance_metadata_source": repair.source,
                            "resonance_metadata_backfilled_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    extra.update(
                        {
                            key: repair.payload[key]
                            for key in (
                                "dimensions",
                                "aligned_count",
                                "aligned_dims",
                                "opposing_dims",
                                "neutral_dims",
                                "adv_usd",
                                "market_cap",
                                "historical_ic",
                                "timing_quality",
                            )
                            if key in repair.payload
                        }
                    )
                    factor.update(repair.payload)
                    factor_signal_dims.update(repair.payload)
                    factor["signal_dimensions"] = factor_signal_dims
                    signal.extra_metadata = extra
                    signal.factor_scores = factor
                    updated_this_signal = True
            else:
                stats.unresolved += 1
                missing_patch = _build_missing_reason_patch(signal)
                if args.apply:
                    extra.update(
                        {
                            "resonance_metadata_status": "MISSING",
                            "resonance_metadata_source": "unavailable",
                            "resonance_metadata_backfilled_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    if missing_patch:
                        extra.update(missing_patch)
                        stats.reason_marked += 1
                    signal.extra_metadata = extra
                    updated_this_signal = True

            if args.apply and updated_this_signal:
                stats.updated += 1

        if args.apply and stats.updated > 0:
            await session.commit()

    return stats


async def run_verify(args: argparse.Namespace) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(args.since_days, 1))
    async with SessionLocal() as session:
        conditions = [
            TradingSignal.created_at >= cutoff,
            TradingSignal.signal_source == SignalSource.STRATEGY,
            TradingSignal.signal_type.in_([SignalType.ENTRY, SignalType.ADD]),
        ]
        if args.account_id:
            conditions.append(TradingSignal.account_id == args.account_id)

        stmt = select(TradingSignal).where(and_(*conditions))
        rows = list((await session.execute(stmt)).scalars().all())
        total = len(rows)
        still_missing = sum(1 for signal in rows if _needs_resonance_backfill(signal))
        missing_reason = 0
        for signal in rows:
            extra = _safe_dict(signal.extra_metadata)
            if extra.get("watchtower_reason_code") == RESONANCE_REASON_CODE:
                missing_reason += 1
        print(f"[VERIFY] total={total} still_missing_resonance={still_missing} marked_missing_reason={missing_reason}")


async def main_async(args: argparse.Namespace) -> None:
    stats = await run_repair(args)
    mode = "APPLY" if args.apply else "CHECK"
    print(f"[{mode}] scanned={stats.scanned}")
    print(f"[{mode}] already_complete={stats.already_complete}")
    print(f"[{mode}] candidates={stats.candidates}")
    print(f"[{mode}] repaired={stats.repaired}")
    print(f"[{mode}] synthesized={stats.synthesized}")
    print(f"[{mode}] unresolved={stats.unresolved}")
    print(f"[{mode}] reason_marked={stats.reason_marked}")
    print(f"[{mode}] updated={stats.updated}")

    if args.apply:
        await run_verify(args)
    else:
        print("[CHECK] dry-run 完成；如需写库，请显式加 --apply")

    await engine.dispose()


def main() -> None:
    args = parse_args()
    if not args.check and not args.apply:
        args.check = True
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
