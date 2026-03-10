from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.models.execution_intent import AutonomousExecutionIntent  # noqa: E402
from app.models.execution_policy_profile import \
    ExecutionPolicyProfile  # noqa: E402
from app.models.execution_quality_log import ExecutionQualityLog  # noqa: E402

ProfileKey = tuple[str, str, str, str, str]


@dataclass
class AggregatedProfile:
    key: ProfileKey
    payload: dict[str, Any]


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_buy_action(action: str) -> bool:
    return str(action or "BUY").upper() in {"BUY", "LONG"}


def _profile_side(action: str) -> str:
    return "BUY" if _is_buy_action(action) else "SELL"


def _running_average(current: float, size: int, new_value: float) -> float:
    if size <= 0:
        return float(new_value)
    return ((current * size) + float(new_value)) / float(size + 1)


def _derive_algo_type(intent: Any, log: Any | None) -> str:
    if log and getattr(log, "algo_type", None):
        return str(log.algo_type).upper()

    qty = abs(_safe_float(getattr(intent, "qty", 0.0)))
    action = str(getattr(intent, "action", "BUY") or "BUY").upper()
    if action in {"SELL", "EXIT", "REDUCE"}:
        return "MARKET"
    if qty >= 1000:
        return "TWAP"
    if qty >= 250:
        return "VWAP"
    if qty >= 75:
        return "LIMIT"
    return "MARKET"


def _derive_urgency(intent: Any, log: Any | None) -> str:
    action = str(getattr(intent, "action", "BUY") or "BUY").upper()
    status = str(getattr(intent, "status", "PENDING") or "PENDING").upper()
    qty = abs(_safe_float(getattr(intent, "qty", 0.0)))
    reason = str(getattr(intent, "reason", "") or "").lower()

    if action in {"SELL", "EXIT", "REDUCE"} or "force" in reason:
        return "FORCED"
    if status in {"FAILED", "REJECTED"}:
        return "HIGH"
    if log and _safe_float(getattr(log, "total_is_bps", None)) >= 25:
        return "HIGH"
    if qty >= 500:
        return "MEDIUM"
    return "LOW"


def _derive_policy_snapshot(intent: Any, log: Any | None) -> dict[str, Any]:
    algo_type = _derive_algo_type(intent, log)
    urgency = _derive_urgency(intent, log)
    action = str(getattr(intent, "action", "BUY") or "BUY").upper()
    qty = abs(_safe_float(getattr(intent, "qty", 0.0)))

    if urgency == "FORCED":
        max_participation_rate = 0.35
        slippage_budget_bps = 35.0
    elif algo_type == "TWAP":
        max_participation_rate = 0.12
        slippage_budget_bps = 14.0
    elif algo_type == "VWAP":
        max_participation_rate = 0.18
        slippage_budget_bps = 18.0
    elif algo_type == "LIMIT":
        max_participation_rate = 0.2
        slippage_budget_bps = 10.0
    else:
        max_participation_rate = 0.25 if qty >= 100 else 0.4
        slippage_budget_bps = 12.0 if qty >= 100 else 8.0

    return {
        "urgency": urgency,
        "algo_type": algo_type,
        "max_participation_rate": round(max_participation_rate, 4),
        "slippage_budget_bps": round(slippage_budget_bps, 2),
        "closing_override_policy": action in {"SELL", "EXIT", "REDUCE"},
    }


def _build_feedback_profile(
    logs: list[ExecutionQualityLog],
    *,
    slippage_budget_bps: float,
) -> dict[str, Any]:
    if not logs:
        return {
            "sample_size": 0,
            "avg_total_is_bps": 0.0,
            "avg_fill_rate": 0.0,
            "avg_quality_score": 0.0,
            "feedback_bias": "NO_DATA",
            "recommended_algo": None,
            "limit_offset_bps": 0.0,
            "participation_rate_multiplier": 1.0,
            "pressure_high": False,
        }

    total_is_values = [_safe_float(log.total_is_bps) for log in logs]
    fill_rates = [_safe_float(log.fill_rate) for log in logs]
    quality_scores = [_safe_float(log.quality_score) for log in logs]
    avg_total_is = sum(total_is_values) / len(total_is_values)
    avg_fill_rate = sum(fill_rates) / len(fill_rates)
    avg_quality_score = sum(quality_scores) / len(quality_scores)
    pressure_high = (
        avg_total_is > max(slippage_budget_bps * 0.85, 12.0)
        or avg_fill_rate < 0.8
        or avg_quality_score < 70.0
    )
    if pressure_high:
        feedback_bias = "DEFENSIVE"
        recommended_algo = "LIMIT"
        limit_offset_bps = 3.5
        participation_rate_multiplier = 0.75
    elif avg_fill_rate >= 0.97 and avg_quality_score >= 85.0:
        feedback_bias = "AGGRESSIVE"
        recommended_algo = None
        limit_offset_bps = 2.5
        participation_rate_multiplier = 1.05
    else:
        feedback_bias = "NEUTRAL"
        recommended_algo = None
        limit_offset_bps = 2.5
        participation_rate_multiplier = 1.0

    return {
        "sample_size": len(logs),
        "avg_total_is_bps": round(avg_total_is, 2),
        "avg_fill_rate": round(avg_fill_rate, 4),
        "avg_quality_score": round(avg_quality_score, 2),
        "feedback_bias": feedback_bias,
        "recommended_algo": recommended_algo,
        "limit_offset_bps": limit_offset_bps,
        "participation_rate_multiplier": participation_rate_multiplier,
        "pressure_high": pressure_high,
    }


def _build_profile_key(
    intent: AutonomousExecutionIntent,
    log: ExecutionQualityLog,
    policy: dict[str, Any],
) -> ProfileKey:
    side = _profile_side(str(getattr(intent, "action", "BUY") or "BUY"))
    urgency = str(policy["urgency"] or "LOW").upper()
    algo_type = str(
        getattr(log, "algo_type", None) or policy["algo_type"] or "MARKET"
    ).upper()
    symbol = str(
        getattr(log, "symbol", None) or getattr(intent, "symbol", "")
    ).upper()
    account_id = str(getattr(intent, "account_id", "") or "")
    return (account_id, symbol, side, urgency, algo_type)


def _ensure_aggregate_profile(
    aggregates: dict[ProfileKey, ExecutionPolicyProfile],
    key: ProfileKey,
) -> ExecutionPolicyProfile:
    profile = aggregates.get(key)
    if profile is not None:
        return profile

    account_id, symbol, side, urgency, algo_type = key
    profile = ExecutionPolicyProfile(
        account_id=account_id,
        symbol=symbol,
        side=side,
        urgency_bucket=urgency,
        algo_type=algo_type,
        sample_size=0,
    )
    aggregates[key] = profile
    return profile


def _apply_log_to_profile(
    profile: ExecutionPolicyProfile,
    log: ExecutionQualityLog,
    feedback: dict[str, Any],
) -> None:
    size = int(profile.sample_size or 0)
    total_is = _safe_float(getattr(log, "total_is_bps", 0.0))
    fill_rate = _safe_float(getattr(log, "fill_rate", 0.0))
    quality_score = _safe_float(getattr(log, "quality_score", 0.0))

    profile.avg_total_is_bps = round(
        _running_average(
            _safe_float(profile.avg_total_is_bps),
            size,
            total_is,
        ),
        4,
    )
    profile.avg_fill_rate = round(
        _running_average(_safe_float(profile.avg_fill_rate), size, fill_rate),
        4,
    )
    profile.avg_quality_score = round(
        _running_average(
            _safe_float(profile.avg_quality_score),
            size,
            quality_score,
        ),
        4,
    )
    profile.sample_size = size + 1
    profile.last_total_is_bps = total_is
    profile.last_fill_rate = fill_rate
    profile.last_quality_score = quality_score
    profile.feedback_bias = str(feedback["feedback_bias"])
    profile.recommended_algo = feedback["recommended_algo"]
    profile.limit_offset_bps = _safe_float(feedback["limit_offset_bps"])
    profile.participation_rate_multiplier = (
        _safe_float(feedback["participation_rate_multiplier"]) or 1.0
    )
    profile.pressure_high = bool(feedback["pressure_high"])
    profile.last_feedback_at = (
        getattr(log, "created_at", None) or datetime.now(timezone.utc)
    )


def _safe_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


async def load_source_rows(
    db: AsyncSession,
    *,
    account_id: str | None = None,
) -> list[tuple[AutonomousExecutionIntent, ExecutionQualityLog]]:
    stmt = (
        select(AutonomousExecutionIntent, ExecutionQualityLog)
        .join(
            ExecutionQualityLog,
            ExecutionQualityLog.intent_id == AutonomousExecutionIntent.id,
        )
        .order_by(
            ExecutionQualityLog.created_at.asc(),
            ExecutionQualityLog.id.asc(),
        )
    )
    if account_id:
        stmt = stmt.where(AutonomousExecutionIntent.account_id == account_id)
    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


def aggregate_profiles(
    rows: Iterable[tuple[AutonomousExecutionIntent, ExecutionQualityLog]],
) -> dict[ProfileKey, AggregatedProfile]:
    aggregates: dict[ProfileKey, ExecutionPolicyProfile] = {}

    for intent, log in rows:
        policy = _derive_policy_snapshot(intent, log)
        feedback = _build_feedback_profile(
            [log],
            slippage_budget_bps=_safe_float(policy["slippage_budget_bps"]),
        )
        key = _build_profile_key(intent, log, policy)
        profile = _ensure_aggregate_profile(aggregates, key)
        _apply_log_to_profile(profile, log, feedback)

    result: dict[ProfileKey, AggregatedProfile] = {}
    for key, profile in aggregates.items():
        result[key] = AggregatedProfile(
            key=key,
            payload={
                "account_id": profile.account_id,
                "symbol": profile.symbol,
                "side": profile.side,
                "urgency_bucket": profile.urgency_bucket,
                "algo_type": profile.algo_type,
                "sample_size": int(profile.sample_size or 0),
                "avg_total_is_bps": float(profile.avg_total_is_bps or 0.0),
                "avg_fill_rate": float(profile.avg_fill_rate or 0.0),
                "avg_quality_score": float(profile.avg_quality_score or 0.0),
                "last_total_is_bps": float(profile.last_total_is_bps or 0.0),
                "last_fill_rate": float(profile.last_fill_rate or 0.0),
                "last_quality_score": float(profile.last_quality_score or 0.0),
                "feedback_bias": str(profile.feedback_bias or "NO_DATA"),
                "recommended_algo": profile.recommended_algo,
                "limit_offset_bps": float(profile.limit_offset_bps or 0.0),
                "participation_rate_multiplier": float(
                    profile.participation_rate_multiplier or 1.0
                ),
                "pressure_high": bool(profile.pressure_high),
                "last_feedback_at": profile.last_feedback_at,
            },
        )
    return result


async def load_existing_profiles(
    db: AsyncSession,
    *,
    account_id: str | None = None,
) -> tuple[
    dict[ProfileKey, ExecutionPolicyProfile],
    dict[ProfileKey, list[int]],
]:
    stmt = select(ExecutionPolicyProfile)
    if account_id:
        stmt = stmt.where(ExecutionPolicyProfile.account_id == account_id)
    rows = list((await db.execute(stmt)).scalars().all())

    profiles: dict[ProfileKey, ExecutionPolicyProfile] = {}
    duplicates: dict[ProfileKey, list[int]] = {}
    for row in rows:
        key: ProfileKey = (
            str(row.account_id),
            str(row.symbol),
            str(row.side),
            str(row.urgency_bucket),
            str(row.algo_type),
        )
        if key in profiles:
            duplicates.setdefault(
                key,
                [int(profiles[key].id)],
            ).append(int(row.id))
            if int(row.sample_size or 0) > int(profiles[key].sample_size or 0):
                profiles[key] = row
        else:
            profiles[key] = row
    return profiles, duplicates


def compare_profile_payload(
    existing: ExecutionPolicyProfile,
    expected: dict[str, Any],
) -> bool:
    fields = [
        "account_id",
        "symbol",
        "side",
        "urgency_bucket",
        "algo_type",
        "sample_size",
        "feedback_bias",
        "recommended_algo",
        "pressure_high",
    ]
    for field in fields:
        if getattr(existing, field) != expected[field]:
            return False

    numeric_fields = [
        "avg_total_is_bps",
        "avg_fill_rate",
        "avg_quality_score",
        "last_total_is_bps",
        "last_fill_rate",
        "last_quality_score",
        "limit_offset_bps",
        "participation_rate_multiplier",
    ]
    for field in numeric_fields:
        if round(float(getattr(existing, field) or 0.0), 4) != round(
            float(expected[field] or 0.0),
            4,
        ):
            return False

    existing_ts = _safe_iso(getattr(existing, "last_feedback_at", None))
    expected_ts = _safe_iso(expected.get("last_feedback_at"))
    return existing_ts == expected_ts


async def replace_profiles(
    db: AsyncSession,
    *,
    expected: dict[ProfileKey, AggregatedProfile],
    account_id: str | None = None,
) -> tuple[int, int]:
    delete_stmt = delete(ExecutionPolicyProfile)
    if account_id:
        delete_stmt = delete_stmt.where(
            ExecutionPolicyProfile.account_id == account_id
        )
    deleted = await db.execute(delete_stmt)

    inserted = 0
    for item in expected.values():
        db.add(ExecutionPolicyProfile(**item.payload))
        inserted += 1
    await db.commit()
    return int(getattr(deleted, "rowcount", 0) or 0), inserted


async def replace_profile_keys(
    db: AsyncSession,
    *,
    keys: list[ProfileKey],
    expected: dict[ProfileKey, AggregatedProfile],
) -> tuple[int, int]:
    if not keys:
        return 0, 0

    deleted = await db.execute(
        delete(ExecutionPolicyProfile).where(
            tuple_(
                ExecutionPolicyProfile.account_id,
                ExecutionPolicyProfile.symbol,
                ExecutionPolicyProfile.side,
                ExecutionPolicyProfile.urgency_bucket,
                ExecutionPolicyProfile.algo_type,
            ).in_(keys)
        )
    )

    inserted = 0
    for key in keys:
        item = expected.get(key)
        if item is None:
            continue
        db.add(ExecutionPolicyProfile(**item.payload))
        inserted += 1
    await db.commit()
    return int(getattr(deleted, "rowcount", 0) or 0), inserted
