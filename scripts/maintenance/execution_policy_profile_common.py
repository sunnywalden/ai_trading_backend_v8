from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.models.execution_intent import AutonomousExecutionIntent
from app.models.execution_policy_profile import ExecutionPolicyProfile
from app.models.execution_quality_log import ExecutionQualityLog
from app.services.execution_policy_service import execution_policy_service

ProfileKey = tuple[str, str, str, str, str]


@dataclass
class AggregatedProfile:
    key: ProfileKey
    payload: dict[str, Any]


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
        .order_by(ExecutionQualityLog.created_at.asc(), ExecutionQualityLog.id.asc())
    )
    if account_id:
        stmt = stmt.where(AutonomousExecutionIntent.account_id == account_id)
    result = await db.execute(stmt)
    return list(result.all())


def aggregate_profiles(
    rows: Iterable[tuple[AutonomousExecutionIntent, ExecutionQualityLog]],
) -> dict[ProfileKey, AggregatedProfile]:
    aggregates: dict[ProfileKey, ExecutionPolicyProfile] = {}

    for intent, log in rows:
        policy = execution_policy_service._derive_policy_snapshot(intent, log)
        feedback = execution_policy_service._build_feedback_profile(
            [log],
            slippage_budget_bps=execution_policy_service._safe_float(
                policy["slippage_budget_bps"]
            ),
        )
        side = execution_policy_service._profile_side(
            str(getattr(intent, "action", "BUY") or "BUY")
        )
        urgency = str(policy["urgency"] or "LOW").upper()
        algo_type = str(
            getattr(log, "algo_type", None) or policy["algo_type"] or "MARKET"
        ).upper()
        symbol = str(
            getattr(log, "symbol", None) or getattr(intent, "symbol", "")
        ).upper()
        account_id = str(getattr(intent, "account_id", "") or "")
        key = (account_id, symbol, side, urgency, algo_type)

        profile = aggregates.get(key)
        if profile is None:
            profile = ExecutionPolicyProfile(
                account_id=account_id,
                symbol=symbol,
                side=side,
                urgency_bucket=urgency,
                algo_type=algo_type,
                sample_size=0,
            )
            aggregates[key] = profile

        size = int(profile.sample_size or 0)
        total_is = execution_policy_service._safe_float(
            getattr(log, "total_is_bps", 0.0)
        )
        fill_rate = execution_policy_service._safe_float(getattr(log, "fill_rate", 0.0))
        quality_score = execution_policy_service._safe_float(
            getattr(log, "quality_score", 0.0)
        )

        profile.avg_total_is_bps = round(
            execution_policy_service._running_average(
                execution_policy_service._safe_float(profile.avg_total_is_bps),
                size,
                total_is,
            ),
            4,
        )
        profile.avg_fill_rate = round(
            execution_policy_service._running_average(
                execution_policy_service._safe_float(profile.avg_fill_rate),
                size,
                fill_rate,
            ),
            4,
        )
        profile.avg_quality_score = round(
            execution_policy_service._running_average(
                execution_policy_service._safe_float(profile.avg_quality_score),
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
        profile.limit_offset_bps = execution_policy_service._safe_float(
            feedback["limit_offset_bps"]
        )
        profile.participation_rate_multiplier = (
            execution_policy_service._safe_float(
                feedback["participation_rate_multiplier"]
            )
            or 1.0
        )
        profile.pressure_high = bool(feedback["pressure_high"])
        profile.last_feedback_at = getattr(log, "created_at", None) or datetime.utcnow()

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
) -> tuple[dict[ProfileKey, ExecutionPolicyProfile], dict[ProfileKey, list[int]]]:
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
            duplicates.setdefault(key, [int(profiles[key].id)]).append(int(row.id))
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
        delete_stmt = delete_stmt.where(ExecutionPolicyProfile.account_id == account_id)
    deleted = await db.execute(delete_stmt)

    inserted = 0
    for item in expected.values():
        db.add(ExecutionPolicyProfile(**item.payload))
        inserted += 1
    await db.commit()
    return int(deleted.rowcount or 0), inserted


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
    return int(deleted.rowcount or 0), inserted
