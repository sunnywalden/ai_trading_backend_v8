from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.execution_policy_profile import ExecutionPolicyProfile
from app.models.execution_quality_log import ExecutionQualityLog


class ExecutionPolicyService:
    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            if value is None:
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _candidate_keys(account_id: str) -> list[str]:
        keys = [str(account_id)]
        if "@" in account_id:
            keys.append(account_id.split("@", 1)[0])
        if account_id.lower().startswith("user_"):
            keys.append(account_id[5:])
        return [key for idx, key in enumerate(keys) if key and key not in keys[:idx]]

    @staticmethod
    def _hard_control_state() -> dict[str, Any]:
        enabled = bool(settings.EXECUTION_POLICY_HARD_CONTROL_ENABLED)
        return {
            "enabled": enabled,
            "mode": "HARD_CONTROL" if enabled else "OBSERVE_ONLY",
        }

    @staticmethod
    def _build_rollout_state() -> dict[str, Any]:
        flags = {
            "execution_policy_hard_control_enabled": bool(
                settings.EXECUTION_POLICY_HARD_CONTROL_ENABLED
            ),
            "signal_pipeline_v1054_enabled": bool(
                settings.SIGNAL_PIPELINE_V1054_ENABLED
            ),
            "autonomous_control_plane_v1054_enabled": bool(
                settings.AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED
            ),
            "native_audit_v1054_enabled": bool(settings.NATIVE_AUDIT_V1054_ENABLED),
            "governance_hard_gate_enabled": bool(settings.GOVERNANCE_HARD_GATE_ENABLED),
        }
        if (
            flags["signal_pipeline_v1054_enabled"]
            and flags["autonomous_control_plane_v1054_enabled"]
            and flags["native_audit_v1054_enabled"]
            and flags["governance_hard_gate_enabled"]
        ):
            stage = "FULL"
        elif (
            flags["autonomous_control_plane_v1054_enabled"]
            and flags["native_audit_v1054_enabled"]
        ):
            stage = "SEMI"
        elif flags["signal_pipeline_v1054_enabled"]:
            stage = "SHADOW"
        else:
            stage = "OBSERVE"
        return {
            "stage": stage,
            "flags": flags,
            "policy_source": "NATIVE_EXECUTION_POLICY",
        }

    @classmethod
    def _derive_algo_type(
        cls,
        intent: Any,
        log: Any | None,
    ) -> str:
        if log and log.algo_type:
            return str(log.algo_type).upper()

        qty = abs(cls._safe_float(getattr(intent, "qty", 0.0)))
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

    @classmethod
    def _derive_urgency(
        cls,
        intent: Any,
        log: Any | None,
    ) -> str:
        action = str(getattr(intent, "action", "BUY") or "BUY").upper()
        status = str(getattr(intent, "status", "PENDING") or "PENDING").upper()
        qty = abs(cls._safe_float(getattr(intent, "qty", 0.0)))
        reason = str(getattr(intent, "reason", "") or "").lower()

        if action in {"SELL", "EXIT", "REDUCE"} or "force" in reason:
            return "FORCED"
        if status in {"FAILED", "REJECTED"}:
            return "HIGH"
        if log and cls._safe_float(log.total_is_bps) >= 25:
            return "HIGH"
        if qty >= 500:
            return "MEDIUM"
        return "LOW"

    @classmethod
    def _derive_policy_snapshot(
        cls,
        intent: Any,
        log: Any | None,
    ) -> dict[str, Any]:
        algo_type = cls._derive_algo_type(intent, log)
        urgency = cls._derive_urgency(intent, log)
        action = str(getattr(intent, "action", "BUY") or "BUY").upper()
        qty = abs(cls._safe_float(getattr(intent, "qty", 0.0)))

        if urgency == "FORCED":
            max_participation_rate = 0.35
            slippage_budget_bps = 35.0
            child_interval_seconds = 0
            cancel_replace_policy = "NO_DELAY_CANCEL_REPLACE"
        elif algo_type == "TWAP":
            max_participation_rate = 0.12
            slippage_budget_bps = 14.0
            child_interval_seconds = 600
            cancel_replace_policy = "PASSIVE_REPRICE"
        elif algo_type == "VWAP":
            max_participation_rate = 0.18
            slippage_budget_bps = 18.0
            child_interval_seconds = 300
            cancel_replace_policy = "VOLUME_CURVE_REPRICE"
        elif algo_type == "LIMIT":
            max_participation_rate = 0.2
            slippage_budget_bps = 10.0
            child_interval_seconds = 120
            cancel_replace_policy = "PEG_TO_MID"
        else:
            max_participation_rate = 0.25 if qty >= 100 else 0.4
            slippage_budget_bps = 12.0 if qty >= 100 else 8.0
            child_interval_seconds = 0
            cancel_replace_policy = "IMMEDIATE_MARKET_CROSS"

        fill_rate = cls._safe_float(getattr(log, "fill_rate", None)) if log else 0.0
        quality_score = (
            cls._safe_float(getattr(log, "quality_score", None)) if log else 0.0
        )
        total_is_bps = (
            cls._safe_float(getattr(log, "total_is_bps", None)) if log else 0.0
        )
        return {
            "urgency": urgency,
            "algo_type": algo_type,
            "max_participation_rate": round(max_participation_rate, 4),
            "slippage_budget_bps": round(slippage_budget_bps, 2),
            "child_order_interval_seconds": child_interval_seconds,
            "cancel_replace_policy": cancel_replace_policy,
            "limit_offset_bps": 2.5 if algo_type == "LIMIT" else 0.0,
            "closing_override_policy": action in {"SELL", "EXIT", "REDUCE"},
            "observed_fill_rate": round(fill_rate, 4),
            "observed_total_is_bps": round(total_is_bps, 2),
            "observed_quality_score": round(quality_score, 2),
        }

    @classmethod
    def _derive_pretrade_cost(
        cls,
        intent: Any,
        log: Any | None,
    ) -> dict[str, Any]:
        qty = abs(cls._safe_float(getattr(intent, "qty", 0.0)))
        notional_bucket = min(max(qty / 100.0, 0.5), 8.0)

        if log:
            delay = cls._safe_float(getattr(log, "delay_cost_bps", None))
            impact = cls._safe_float(getattr(log, "market_impact_bps", None))
            opportunity = cls._safe_float(getattr(log, "opportunity_cost_bps", None))
            timing = cls._safe_float(getattr(log, "timing_cost_bps", None))
        else:
            delay = round(1.5 + 0.9 * notional_bucket, 2)
            impact = round(2.0 + 1.2 * notional_bucket, 2)
            opportunity = round(1.0 + 0.8 * notional_bucket, 2)
            timing = round(1.2 + 0.7 * notional_bucket, 2)

        spread_cost = round(max(0.8, delay * 0.6), 2)
        total = round(delay + impact + opportunity + timing, 2)
        return {
            "spread_cost_bps": spread_cost,
            "delay_cost_bps": round(delay, 2),
            "market_impact_bps": round(impact, 2),
            "opportunity_cost_bps": round(opportunity, 2),
            "timing_cost_bps": round(timing, 2),
            "total_expected_cost_bps": total,
        }

    @staticmethod
    def _is_buy_action(action: str) -> bool:
        return str(action or "BUY").upper() in {"BUY", "LONG"}

    @classmethod
    def _apply_limit_offset(
        cls,
        reference_price: float,
        action: str,
        offset_bps: float,
    ) -> float | None:
        if reference_price <= 0:
            return None
        offset_ratio = cls._safe_float(offset_bps) / 10000.0
        multiplier = (
            1.0 + offset_ratio if cls._is_buy_action(action) else 1.0 - offset_ratio
        )
        return round(reference_price * multiplier, 4)

    @classmethod
    def _should_force_limit(
        cls,
        policy: dict[str, Any],
        pretrade: dict[str, Any],
    ) -> bool:
        return pretrade["total_expected_cost_bps"] > policy[
            "slippage_budget_bps"
        ] and policy["urgency"] not in {"FORCED", "HIGH"}

    @classmethod
    def build_live_execution_controls(
        cls,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        action = str(decision.get("action") or "BUY").upper()
        intent = SimpleNamespace(
            action=action,
            qty=decision.get("qty"),
            reason=(
                decision.get("reason")
                or decision.get("reasoning")
                or decision.get("execution_path")
            ),
            status="PENDING",
        )
        policy = cls._derive_policy_snapshot(intent, None)
        pretrade = cls._derive_pretrade_cost(intent, None)
        control_state = cls._hard_control_state()

        requested_algo = str(
            decision.get("algo") or decision.get("order_type") or "MARKET"
        ).upper()
        if requested_algo == "MKT":
            requested_algo = "MARKET"

        effective_algo = requested_algo
        if control_state["enabled"]:
            effective_algo = str(policy["algo_type"] or "MARKET").upper()
            if cls._should_force_limit(policy, pretrade):
                effective_algo = "LIMIT"
            if policy["closing_override_policy"]:
                effective_algo = "MARKET"

        reference_price = cls._safe_float(
            decision.get("ref_price")
            or decision.get("price")
            or decision.get("arrival_price")
        )
        limit_price = None
        if effective_algo == "LIMIT":
            limit_offset_bps = cls._safe_float(policy.get("limit_offset_bps"))
            if limit_offset_bps <= 0:
                limit_offset_bps = 2.5
            limit_price = cls._apply_limit_offset(
                reference_price,
                action,
                limit_offset_bps,
            )

        broker_order_type = "LMT" if effective_algo == "LIMIT" else effective_algo
        return {
            "control_state": control_state,
            "policy": policy,
            "pretrade_cost": pretrade,
            "requested_algo": requested_algo,
            "effective_algo": effective_algo,
            "broker_order_type": broker_order_type,
            "limit_price": limit_price,
            "budget_breached": (
                pretrade["total_expected_cost_bps"] > policy["slippage_budget_bps"]
            ),
        }

    @classmethod
    def _build_feedback_profile(
        cls,
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

        total_is_values = [cls._safe_float(log.total_is_bps) for log in logs]
        fill_rates = [cls._safe_float(log.fill_rate) for log in logs]
        quality_scores = [cls._safe_float(log.quality_score) for log in logs]
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

    @staticmethod
    def _profile_side(action: str) -> str:
        return "BUY" if ExecutionPolicyService._is_buy_action(action) else "SELL"

    @staticmethod
    def _running_average(current: float, size: int, new_value: float) -> float:
        if size <= 0:
            return float(new_value)
        return ((current * size) + float(new_value)) / float(size + 1)

    @classmethod
    def _feedback_profile_from_persistent_profile(
        cls,
        profile: ExecutionPolicyProfile,
    ) -> dict[str, Any]:
        return {
            "sample_size": int(profile.sample_size or 0),
            "avg_total_is_bps": round(
                cls._safe_float(profile.avg_total_is_bps),
                2,
            ),
            "avg_fill_rate": round(
                cls._safe_float(profile.avg_fill_rate),
                4,
            ),
            "avg_quality_score": round(
                cls._safe_float(profile.avg_quality_score),
                2,
            ),
            "feedback_bias": str(profile.feedback_bias or "NO_DATA"),
            "recommended_algo": (
                str(profile.recommended_algo).upper()
                if profile.recommended_algo
                else None
            ),
            "limit_offset_bps": round(
                cls._safe_float(profile.limit_offset_bps),
                2,
            ),
            "participation_rate_multiplier": round(
                cls._safe_float(profile.participation_rate_multiplier) or 1.0,
                4,
            ),
            "pressure_high": bool(profile.pressure_high),
            "source": "persistent_profile",
        }

    @staticmethod
    def _serialize_persistent_profile(
        profile: ExecutionPolicyProfile | None,
    ) -> dict[str, Any] | None:
        if profile is None:
            return None
        return {
            "id": int(profile.id),
            "account_id": str(profile.account_id),
            "symbol": str(profile.symbol),
            "side": str(profile.side),
            "urgency_bucket": str(profile.urgency_bucket),
            "algo_type": str(profile.algo_type),
            "sample_size": int(profile.sample_size or 0),
            "avg_total_is_bps": round(
                float(profile.avg_total_is_bps or 0.0),
                2,
            ),
            "avg_fill_rate": round(float(profile.avg_fill_rate or 0.0), 4),
            "avg_quality_score": round(
                float(profile.avg_quality_score or 0.0),
                2,
            ),
            "feedback_bias": str(profile.feedback_bias or "NO_DATA"),
            "recommended_algo": (
                str(profile.recommended_algo).upper()
                if profile.recommended_algo
                else None
            ),
            "limit_offset_bps": round(
                float(profile.limit_offset_bps or 0.0),
                2,
            ),
            "participation_rate_multiplier": round(
                float(profile.participation_rate_multiplier or 1.0),
                4,
            ),
            "pressure_high": bool(profile.pressure_high),
            "last_feedback_at": (
                profile.last_feedback_at.isoformat()
                if profile.last_feedback_at
                else None
            ),
        }

    @classmethod
    def _select_best_profile(
        cls,
        profiles: list[ExecutionPolicyProfile],
        preferred_algo: str,
        urgency: str,
    ) -> ExecutionPolicyProfile | None:
        if not profiles:
            return None

        preferred_algo_upper = str(preferred_algo or "").upper()
        urgency_upper = str(urgency or "").upper()
        exact = [
            profile
            for profile in profiles
            if str(profile.algo_type or "").upper() == preferred_algo_upper
            and str(profile.urgency_bucket or "").upper() == urgency_upper
        ]
        if exact:
            return max(
                exact,
                key=lambda profile: (
                    int(profile.sample_size or 0),
                    profile.last_feedback_at or datetime.min,
                ),
            )

        urgency_matches = [
            profile
            for profile in profiles
            if str(profile.urgency_bucket or "").upper() == urgency_upper
        ]
        if urgency_matches:
            return max(
                urgency_matches,
                key=lambda profile: (
                    int(profile.sample_size or 0),
                    profile.last_feedback_at or datetime.min,
                ),
            )

        return max(
            profiles,
            key=lambda profile: (
                int(profile.sample_size or 0),
                profile.last_feedback_at or datetime.min,
            ),
        )

    async def _load_persistent_feedback_profile(
        self,
        db: AsyncSession,
        account_id: str,
        symbol: str,
        side: str,
        urgency: str,
        preferred_algo: str,
    ) -> ExecutionPolicyProfile | None:
        if not symbol:
            return None

        stmt = (
            select(ExecutionPolicyProfile)
            .where(
                ExecutionPolicyProfile.account_id.in_(self._candidate_keys(account_id))
            )
            .where(ExecutionPolicyProfile.symbol == symbol)
            .where(ExecutionPolicyProfile.side == side)
            .order_by(desc(ExecutionPolicyProfile.last_feedback_at))
            .limit(16)
        )
        profiles = list((await db.execute(stmt)).scalars().all())
        return self._select_best_profile(profiles, preferred_algo, urgency)

    async def update_persistent_feedback_profile_from_execution(
        self,
        db: AsyncSession,
        *,
        account_id: str,
        symbol: str,
        intent: Any,
        log: Any,
    ) -> ExecutionPolicyProfile:
        policy = self._derive_policy_snapshot(intent, log)
        feedback_profile = self._build_feedback_profile(
            [log],
            slippage_budget_bps=self._safe_float(policy["slippage_budget_bps"]),
        )
        side = self._profile_side(str(intent.action or "BUY"))
        urgency = str(policy["urgency"] or "LOW").upper()
        algo_type = str(
            getattr(log, "algo_type", None) or policy["algo_type"] or "MARKET"
        ).upper()
        normalized_symbol = str(symbol or getattr(intent, "symbol", "")).upper()

        stmt = (
            select(ExecutionPolicyProfile)
            .where(ExecutionPolicyProfile.account_id == account_id)
            .where(ExecutionPolicyProfile.symbol == normalized_symbol)
            .where(ExecutionPolicyProfile.side == side)
            .where(ExecutionPolicyProfile.urgency_bucket == urgency)
            .where(ExecutionPolicyProfile.algo_type == algo_type)
            .limit(1)
        )
        profile = (await db.execute(stmt)).scalars().one_or_none()
        if profile is None:
            profile = ExecutionPolicyProfile(
                account_id=account_id,
                symbol=normalized_symbol,
                side=side,
                urgency_bucket=urgency,
                algo_type=algo_type,
                sample_size=0,
            )
            db.add(profile)
            await db.flush()

        size = int(profile.sample_size or 0)
        total_is = self._safe_float(getattr(log, "total_is_bps", 0.0))
        fill_rate = self._safe_float(getattr(log, "fill_rate", 0.0))
        quality_score = self._safe_float(getattr(log, "quality_score", 0.0))

        profile.avg_total_is_bps = round(
            self._running_average(
                self._safe_float(profile.avg_total_is_bps),
                size,
                total_is,
            ),
            4,
        )
        profile.avg_fill_rate = round(
            self._running_average(
                self._safe_float(profile.avg_fill_rate),
                size,
                fill_rate,
            ),
            4,
        )
        profile.avg_quality_score = round(
            self._running_average(
                self._safe_float(profile.avg_quality_score),
                size,
                quality_score,
            ),
            4,
        )
        profile.sample_size = size + 1
        profile.last_total_is_bps = total_is
        profile.last_fill_rate = fill_rate
        profile.last_quality_score = quality_score
        profile.feedback_bias = str(feedback_profile["feedback_bias"])
        profile.recommended_algo = feedback_profile["recommended_algo"]
        profile.limit_offset_bps = self._safe_float(
            feedback_profile["limit_offset_bps"]
        )
        profile.participation_rate_multiplier = (
            self._safe_float(feedback_profile["participation_rate_multiplier"]) or 1.0
        )
        profile.pressure_high = bool(feedback_profile["pressure_high"])
        profile.last_feedback_at = getattr(log, "created_at", None) or datetime.now()

        await db.commit()
        await db.refresh(profile)
        return profile

    async def _load_recent_feedback_logs(
        self,
        db: AsyncSession,
        account_id: str,
        symbol: str,
    ) -> list[ExecutionQualityLog]:
        if not symbol:
            return []

        try:
            stmt = (
                select(ExecutionQualityLog)
                .where(
                    ExecutionQualityLog.account_id.in_(self._candidate_keys(account_id))
                )
                .where(ExecutionQualityLog.symbol == symbol)
                .order_by(desc(ExecutionQualityLog.created_at))
                .limit(12)
            )
            return list((await db.execute(stmt)).scalars().all())
        except SQLAlchemyError:
            return []

    async def _safe_load_profile(
        self,
        db: AsyncSession,
        account_id: str,
        symbol: str,
        side: str,
        urgency: str,
        preferred_algo: str,
    ) -> ExecutionPolicyProfile | None:
        try:
            return await self._load_persistent_feedback_profile(
                db,
                account_id,
                symbol,
                side,
                urgency,
                preferred_algo,
            )
        except SQLAlchemyError:
            return None

    def _resolve_feedback_profile(
        self,
        *,
        logs: list[ExecutionQualityLog],
        persistent_profile: ExecutionPolicyProfile | None,
        slippage_budget_bps: float,
    ) -> dict[str, Any]:
        if logs:
            feedback_profile = self._build_feedback_profile(
                logs,
                slippage_budget_bps=slippage_budget_bps,
            )
            feedback_profile["source"] = "recent_logs"
            return feedback_profile

        if persistent_profile is not None:
            return self._feedback_profile_from_persistent_profile(persistent_profile)

        feedback_profile = self._build_feedback_profile(
            [],
            slippage_budget_bps=slippage_budget_bps,
        )
        feedback_profile["source"] = "none"
        return feedback_profile

    @classmethod
    def _derive_profile_lookup_inputs(
        cls,
        intent: Any,
        log: Any | None,
    ) -> dict[str, Any]:
        policy = cls._derive_policy_snapshot(intent, log)
        preferred_algo = str(
            getattr(log, "algo_type", None) or policy["algo_type"] or "MARKET"
        ).upper()
        return {
            "symbol": str(getattr(intent, "symbol", "") or "").upper(),
            "side": cls._profile_side(str(getattr(intent, "action", "BUY") or "BUY")),
            "urgency": str(policy["urgency"] or "LOW").upper(),
            "preferred_algo": preferred_algo,
        }

    async def _load_profiles_for_symbols(
        self,
        db: AsyncSession,
        account_id: str,
        symbols: list[str],
    ) -> dict[str, list[ExecutionPolicyProfile]]:
        normalized_symbols = sorted(
            {str(symbol or "").upper() for symbol in symbols if symbol}
        )
        if not normalized_symbols:
            return {}

        try:
            stmt = (
                select(ExecutionPolicyProfile)
                .where(
                    ExecutionPolicyProfile.account_id.in_(
                        self._candidate_keys(account_id)
                    )
                )
                .where(ExecutionPolicyProfile.symbol.in_(normalized_symbols))
                .order_by(desc(ExecutionPolicyProfile.last_feedback_at))
            )
            profiles = list((await db.execute(stmt)).scalars().all())
        except SQLAlchemyError:
            return {}

        profiles_by_symbol: dict[str, list[ExecutionPolicyProfile]] = {}
        for profile in profiles:
            profiles_by_symbol.setdefault(str(profile.symbol), []).append(profile)
        return profiles_by_symbol

    def _match_persistent_profile_for_intent(
        self,
        intent: Any,
        log: Any | None,
        profiles_by_symbol: dict[str, list[ExecutionPolicyProfile]],
    ) -> ExecutionPolicyProfile | None:
        lookup = self._derive_profile_lookup_inputs(intent, log)
        candidates = [
            profile
            for profile in profiles_by_symbol.get(lookup["symbol"], [])
            if str(profile.side or "").upper() == lookup["side"]
        ]
        return self._select_best_profile(
            candidates,
            lookup["preferred_algo"],
            lookup["urgency"],
        )

    async def build_live_execution_controls_with_feedback(
        self,
        db: AsyncSession,
        account_id: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        controls = self.build_live_execution_controls(decision)
        symbol = str(decision.get("symbol") or "").strip().upper()
        side = self._profile_side(str(decision.get("action") or "BUY"))
        urgency = str(controls["policy"]["urgency"] or "LOW").upper()
        logs = await self._load_recent_feedback_logs(db, account_id, symbol)
        preferred_algo = str(controls["effective_algo"] or controls["requested_algo"])
        persistent_profile = await self._safe_load_profile(
            db,
            account_id,
            symbol,
            side,
            urgency,
            preferred_algo,
        )
        feedback_profile = self._resolve_feedback_profile(
            logs=logs,
            persistent_profile=persistent_profile,
            slippage_budget_bps=self._safe_float(
                controls["policy"]["slippage_budget_bps"]
            ),
        )

        controls["feedback_profile"] = feedback_profile
        controls["persistent_profile"] = self._serialize_persistent_profile(
            persistent_profile
        )

        policy = dict(controls["policy"])
        policy["feedback_bias"] = feedback_profile["feedback_bias"]
        policy["recent_feedback_sample_size"] = feedback_profile["sample_size"]
        policy["recent_avg_total_is_bps"] = feedback_profile["avg_total_is_bps"]
        policy["recent_avg_fill_rate"] = feedback_profile["avg_fill_rate"]
        policy["recent_avg_quality_score"] = feedback_profile["avg_quality_score"]
        policy["max_participation_rate"] = round(
            self._safe_float(policy["max_participation_rate"])
            * self._safe_float(feedback_profile["participation_rate_multiplier"]),
            4,
        )

        if (
            controls["control_state"]["enabled"]
            and feedback_profile["recommended_algo"] == "LIMIT"
            and not policy["closing_override_policy"]
        ):
            controls["effective_algo"] = "LIMIT"

        if controls["effective_algo"] == "LIMIT":
            reference_price = self._safe_float(
                decision.get("ref_price")
                or decision.get("price")
                or decision.get("arrival_price")
            )
            controls["limit_price"] = self._apply_limit_offset(
                reference_price,
                str(decision.get("action") or "BUY").upper(),
                max(
                    self._safe_float(policy.get("limit_offset_bps")),
                    self._safe_float(feedback_profile["limit_offset_bps"]),
                    2.5,
                ),
            )

        controls["policy"] = policy
        controls["broker_order_type"] = (
            "LMT"
            if controls["effective_algo"] == "LIMIT"
            else controls["effective_algo"]
        )
        controls["budget_breached"] = controls["budget_breached"] or bool(
            feedback_profile["pressure_high"]
        )
        return controls

    @classmethod
    def _build_replay_timeline(
        cls,
        intent: Any,
        log: Any | None,
        policy: dict[str, Any],
    ) -> list[dict[str, Any]]:
        created_at = intent.created_at or datetime.now()
        fill_ms = (
            int(cls._safe_float(getattr(log, "time_to_fill_ms", None))) if log else 0
        )
        fill_at = (
            created_at + timedelta(milliseconds=fill_ms) if fill_ms > 0 else created_at
        )

        timeline = [
            {
                "phase": "ARRIVAL",
                "timestamp": created_at.isoformat() if created_at else None,
                "label": "策略信号进入执行层",
            },
            {
                "phase": "POLICY_ASSIGNED",
                "timestamp": created_at.isoformat() if created_at else None,
                "label": (
                    f"{policy['algo_type']} / {policy['urgency']} " "policy assigned"
                ),
            },
        ]

        if policy["child_order_interval_seconds"] > 0:
            slices = 3 if policy["algo_type"] == "VWAP" else 4
            for index in range(slices):
                slice_ts = created_at + timedelta(
                    seconds=policy["child_order_interval_seconds"] * index
                )
                timeline.append(
                    {
                        "phase": "CHILD_ORDER",
                        "timestamp": slice_ts.isoformat(),
                        "label": f"Slice {index + 1} routed",
                    }
                )
        else:
            timeline.append(
                {
                    "phase": "ORDER_SUBMITTED",
                    "timestamp": (created_at.isoformat() if created_at else None),
                    "label": "Parent order submitted",
                }
            )

        timeline.append(
            {
                "phase": "FILL_COMPLETE",
                "timestamp": fill_at.isoformat() if fill_at else None,
                "label": f"Execution finished with status {intent.status}",
            }
        )
        return timeline

    @classmethod
    def _build_exceptions(
        cls,
        intent: Any,
        log: Any | None,
        policy: dict[str, Any],
    ) -> list[dict[str, Any]]:
        exceptions: list[dict[str, Any]] = []
        reason = str(intent.reason or "").strip()
        if reason:
            exceptions.append(
                {
                    "type": "INTENT_REASON",
                    "severity": ("medium" if intent.status == "SUCCESS" else "high"),
                    "message": reason,
                }
            )
        if log and cls._safe_float(log.total_is_bps) > policy["slippage_budget_bps"]:
            exceptions.append(
                {
                    "type": "SLIPPAGE_BUDGET_BREACH",
                    "severity": "high",
                    "message": (
                        f"Observed IS {log.total_is_bps:.1f}bps exceeded "
                        f"budget {policy['slippage_budget_bps']:.1f}bps"
                    ),
                }
            )
        if log and cls._safe_float(log.fill_rate) < 0.75:
            exceptions.append(
                {
                    "type": "LOW_FILL_RATE",
                    "severity": "medium",
                    "message": (
                        "Fill rate dropped to "
                        f"{cls._safe_float(log.fill_rate) * 100:.1f}%"
                    ),
                }
            )
        if not exceptions:
            exceptions.append(
                {
                    "type": "NONE",
                    "severity": "info",
                    "message": "No execution anomalies detected.",
                }
            )
        return exceptions

    @staticmethod
    def _build_overview_lookup(
        order_id_filter: str | None,
        intents: list[AutonomousExecutionIntent],
        matched_exactly: bool,
    ) -> dict[str, Any] | None:
        if not order_id_filter:
            return None
        if matched_exactly:
            match_mode = "order_id"
        else:
            match_mode = "fallback_filters" if intents else "not_found"
        return {
            "requested_order_id": order_id_filter,
            "match_mode": match_mode,
        }

    @staticmethod
    def _latest_log_sort_key(log: Any) -> tuple[datetime, int]:
        created_at = getattr(log, "created_at", None) or datetime.min
        log_id = getattr(log, "id", None) or 0
        return (created_at, int(log_id))

    @classmethod
    def _build_latest_logs_by_intent(
        cls,
        logs: list[ExecutionQualityLog],
    ) -> dict[int, ExecutionQualityLog]:
        latest: dict[int, ExecutionQualityLog] = {}
        for log in logs:
            intent_id = int(getattr(log, "intent_id", 0) or 0)
            if intent_id <= 0:
                continue
            current = latest.get(intent_id)
            if current is None or cls._latest_log_sort_key(
                log
            ) > cls._latest_log_sort_key(current):
                latest[intent_id] = log
        return latest

    async def _select_overview_intents(
        self,
        db: AsyncSession,
        base_stmt: Any,
        limit: int,
        order_id_filter: str | None,
    ) -> tuple[list[AutonomousExecutionIntent], dict[str, Any] | None]:
        if order_id_filter:
            exact_stmt = (
                base_stmt.where(AutonomousExecutionIntent.order_id == order_id_filter)
                .order_by(desc(AutonomousExecutionIntent.created_at))
                .limit(limit)
            )
            _rows = await db.execute(exact_stmt)
            exact_intents = list(_rows.scalars().all())
            if exact_intents:
                return exact_intents, self._build_overview_lookup(
                    order_id_filter,
                    exact_intents,
                    True,
                )

        intent_stmt = base_stmt.order_by(
            desc(AutonomousExecutionIntent.created_at)
        ).limit(max(limit * 3, 30))
        intents = list((await db.execute(intent_stmt)).scalars().all())
        return intents, self._build_overview_lookup(
            order_id_filter,
            intents,
            False,
        )

    def _accumulate_policy_rows(
        self,
        intents: list,
        logs_by_intent: dict,
        profiles_by_symbol: dict[str, list[ExecutionPolicyProfile]] | None = None,
    ) -> dict[str, Any]:
        rows: list[dict] = []
        total_budget = 0.0
        realized: list[float] = []
        forced = 0
        high_urgency = 0
        matched_profiles: list[ExecutionPolicyProfile] = []
        profile_lookup = profiles_by_symbol or {}
        for intent in intents:
            log = logs_by_intent.get(int(intent.id))
            policy = self._derive_policy_snapshot(intent, log)
            pretrade = self._derive_pretrade_cost(intent, log)
            matched_profile = self._match_persistent_profile_for_intent(
                intent,
                log,
                profile_lookup,
            )
            if policy["urgency"] == "FORCED":
                forced += 1
            if policy["urgency"] in {"HIGH", "FORCED"}:
                high_urgency += 1
            total_budget += self._safe_float(policy["slippage_budget_bps"])
            if log:
                realized.append(self._safe_float(log.total_is_bps))
            if matched_profile is not None:
                matched_profiles.append(matched_profile)
            rows.append(
                {
                    "intent_id": intent.id,
                    "intent_key": intent.intent_id,
                    "order_id": intent.order_id,
                    "symbol": intent.symbol,
                    "action": intent.action,
                    "status": intent.status,
                    "qty": self._safe_float(intent.qty),
                    "created_at": (
                        intent.created_at.isoformat() if intent.created_at else None
                    ),
                    "policy": policy,
                    "pretrade_cost": pretrade,
                    "grade": getattr(log, "grade", None),
                    "policy_source": "NATIVE_EXECUTION_POLICY",
                    "feedback_source": (
                        "recent_logs"
                        if log is not None
                        else (
                            "persistent_profile"
                            if matched_profile is not None
                            else "none"
                        )
                    ),
                    "persistent_profile": self._serialize_persistent_profile(
                        matched_profile
                    ),
                }
            )
        return {
            "rows": rows,
            "total_budget": total_budget,
            "realized": realized,
            "forced": forced,
            "high_urgency": high_urgency,
            "matched_profiles": matched_profiles,
        }

    async def get_policy_overview(
        self,
        db: AsyncSession,
        account_id: str,
        limit: int = 20,
        symbol: str | None = None,
        action: str | None = None,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        keys = self._candidate_keys(account_id)
        symbol_filter = str(symbol or "").strip().upper() or None
        action_filter = str(action or "").strip().upper() or None
        order_id_filter = str(order_id or "").strip() or None
        base_stmt = select(AutonomousExecutionIntent).where(
            AutonomousExecutionIntent.account_id.in_(keys)
        )
        if symbol_filter:
            base_stmt = base_stmt.where(
                AutonomousExecutionIntent.symbol == symbol_filter
            )
        if action_filter:
            base_stmt = base_stmt.where(
                AutonomousExecutionIntent.action == action_filter
            )
        intents, lookup = await self._select_overview_intents(
            db,
            base_stmt,
            limit,
            order_id_filter,
        )

        if not intents:
            return {
                "summary": {
                    "total": 0,
                    "forced": 0,
                    "high_urgency": 0,
                    "avg_slippage_budget_bps": 0.0,
                    "avg_realized_is_bps": 0.0,
                },
                "policies": [],
                "lookup": lookup,
                "control_state": self._hard_control_state(),
                "rollout": self._build_rollout_state(),
            }

        intent_ids = [int(intent.id) for intent in intents]
        log_stmt = select(ExecutionQualityLog).where(
            ExecutionQualityLog.intent_id.in_(intent_ids)
        )
        logs = list((await db.execute(log_stmt)).scalars().all())
        logs_by_intent = self._build_latest_logs_by_intent(logs)
        profiles_by_symbol = await self._load_profiles_for_symbols(
            db,
            account_id,
            [intent.symbol for intent in intents[:limit]],
        )

        acc = self._accumulate_policy_rows(
            intents[:limit],
            logs_by_intent,
            profiles_by_symbol,
        )
        policy_rows = acc["rows"]
        realized = acc["realized"]
        matched_profiles = acc["matched_profiles"]
        unique_profiles: dict[int, ExecutionPolicyProfile] = {
            int(profile.id): profile
            for profile in matched_profiles
            if getattr(profile, "id", None) is not None
        }
        return {
            "summary": {
                "total": len(policy_rows),
                "forced": acc["forced"],
                "high_urgency": acc["high_urgency"],
                "avg_slippage_budget_bps": (
                    round(acc["total_budget"] / len(policy_rows), 2)
                    if policy_rows
                    else 0.0
                ),
                "avg_realized_is_bps": (
                    round(sum(realized) / len(realized), 2) if realized else 0.0
                ),
                "persistent_profile_matches": len(matched_profiles),
                "persistent_profile_coverage": (
                    round(len(matched_profiles) / len(policy_rows), 4)
                    if policy_rows
                    else 0.0
                ),
            },
            "policies": policy_rows,
            "persistent_profiles": [
                self._serialize_persistent_profile(profile)
                for profile in unique_profiles.values()
            ],
            "lookup": lookup,
            "control_state": self._hard_control_state(),
            "rollout": self._build_rollout_state(),
        }

    async def get_policy_detail(
        self,
        db: AsyncSession,
        account_id: str,
        intent_id: int,
    ) -> dict[str, Any] | None:
        keys = self._candidate_keys(account_id)
        intent_stmt = select(AutonomousExecutionIntent).where(
            AutonomousExecutionIntent.id == intent_id,
            AutonomousExecutionIntent.account_id.in_(keys),
        )
        intent = (await db.execute(intent_stmt)).scalars().one_or_none()
        if intent is None:
            return None

        log_stmt = select(ExecutionQualityLog).where(
            ExecutionQualityLog.intent_id == intent_id
        )
        logs = list((await db.execute(log_stmt)).scalars().all())
        log = self._build_latest_logs_by_intent(logs).get(intent_id)
        policy = self._derive_policy_snapshot(intent, log)
        pretrade = self._derive_pretrade_cost(intent, log)
        timeline = self._build_replay_timeline(intent, log, policy)
        exceptions = self._build_exceptions(intent, log, policy)
        profile_lookup = self._derive_profile_lookup_inputs(intent, log)
        persistent_profile = await self._safe_load_profile(
            db,
            account_id,
            profile_lookup["symbol"],
            profile_lookup["side"],
            profile_lookup["urgency"],
            profile_lookup["preferred_algo"],
        )
        feedback_profile = self._resolve_feedback_profile(
            logs=[log] if log is not None else [],
            persistent_profile=persistent_profile,
            slippage_budget_bps=self._safe_float(policy["slippage_budget_bps"]),
        )

        execution_result = None
        if log:
            execution_result = {
                "grade": log.grade,
                "quality_score": self._safe_float(log.quality_score),
                "total_is_bps": self._safe_float(log.total_is_bps),
                "fill_rate": self._safe_float(log.fill_rate),
                "time_to_fill_ms": int(self._safe_float(log.time_to_fill_ms)),
                "arrival_price": self._safe_float(log.arrival_price),
                "fill_price": self._safe_float(log.fill_price),
                "mid_price_at_order": self._safe_float(log.mid_price_at_order),
                "vwap_reference": self._safe_float(log.vwap_reference),
            }

        return {
            "intent": {
                "id": intent.id,
                "intent_id": intent.intent_id,
                "idempotency_key": intent.idempotency_key,
                "symbol": intent.symbol,
                "action": intent.action,
                "status": intent.status,
                "qty": self._safe_float(intent.qty),
                "order_id": intent.order_id,
                "reason": intent.reason,
                "created_at": (
                    intent.created_at.isoformat() if intent.created_at else None
                ),
                "updated_at": (
                    intent.updated_at.isoformat() if intent.updated_at else None
                ),
            },
            "policy": policy,
            "pretrade_cost": pretrade,
            "control_state": self._hard_control_state(),
            "policy_source": "NATIVE_EXECUTION_POLICY",
            "feedback_profile": feedback_profile,
            "persistent_profile": self._serialize_persistent_profile(
                persistent_profile
            ),
            "timeline": timeline,
            "exceptions": exceptions,
            "execution_result": execution_result,
            "rollout": self._build_rollout_state(),
        }


execution_policy_service = ExecutionPolicyService()
