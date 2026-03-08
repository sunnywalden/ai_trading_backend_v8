from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_intent import AutonomousExecutionIntent
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
        return [
            key
            for idx, key in enumerate(keys)
            if key and key not in keys[:idx]
        ]

    @classmethod
    def _derive_algo_type(
        cls,
        intent: Any,
        log: Any | None,
    ) -> str:
        if log and log.algo_type:
            return str(log.algo_type).upper()

        qty = abs(cls._safe_float(intent.qty))
        action = str(intent.action or "BUY").upper()
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
        action = str(intent.action or "BUY").upper()
        status = str(intent.status or "PENDING").upper()
        qty = abs(cls._safe_float(intent.qty))
        reason = str(intent.reason or "").lower()

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
        action = str(intent.action or "BUY").upper()
        qty = abs(cls._safe_float(intent.qty))

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

        fill_rate = (
            cls._safe_float(getattr(log, "fill_rate", None)) if log else 0.0
        )
        quality_score = (
            cls._safe_float(getattr(log, "quality_score", None))
            if log
            else 0.0
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
        qty = abs(cls._safe_float(intent.qty))
        notional_bucket = min(max(qty / 100.0, 0.5), 8.0)

        if log:
            delay = cls._safe_float(log.delay_cost_bps)
            impact = cls._safe_float(log.market_impact_bps)
            opportunity = cls._safe_float(log.opportunity_cost_bps)
            timing = cls._safe_float(log.timing_cost_bps)
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

    @classmethod
    def _build_replay_timeline(
        cls,
        intent: Any,
        log: Any | None,
        policy: dict[str, Any],
    ) -> list[dict[str, Any]]:
        created_at = intent.created_at or datetime.now()
        fill_ms = (
            int(cls._safe_float(getattr(log, "time_to_fill_ms", None)))
            if log
            else 0
        )
        fill_at = (
            created_at + timedelta(milliseconds=fill_ms)
            if fill_ms > 0
            else created_at
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
                    f"{policy['algo_type']} / {policy['urgency']} "
                    "policy assigned"
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
                    "timestamp": (
                        created_at.isoformat() if created_at else None
                    ),
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
                    "severity": (
                        "medium" if intent.status == "SUCCESS" else "high"
                    ),
                    "message": reason,
                }
            )
        if log and cls._safe_float(log.total_is_bps) > policy[
            "slippage_budget_bps"
        ]:
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

    async def _select_overview_intents(
        self,
        db: AsyncSession,
        base_stmt: Any,
        limit: int,
        order_id_filter: str | None,
    ) -> tuple[list[AutonomousExecutionIntent], dict[str, Any] | None]:
        if order_id_filter:
            exact_stmt = base_stmt.where(
                AutonomousExecutionIntent.order_id == order_id_filter
            ).order_by(desc(AutonomousExecutionIntent.created_at)).limit(limit)
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
    ) -> dict[str, Any]:
        rows: list[dict] = []
        total_budget = 0.0
        realized: list[float] = []
        forced = 0
        high_urgency = 0
        for intent in intents:
            log = logs_by_intent.get(int(intent.id))
            policy = self._derive_policy_snapshot(intent, log)
            pretrade = self._derive_pretrade_cost(intent, log)
            if policy["urgency"] == "FORCED":
                forced += 1
            if policy["urgency"] in {"HIGH", "FORCED"}:
                high_urgency += 1
            total_budget += self._safe_float(
                policy["slippage_budget_bps"]
            )
            if log:
                realized.append(self._safe_float(log.total_is_bps))
            rows.append({
                "intent_id": intent.id,
                "intent_key": intent.intent_id,
                "order_id": intent.order_id,
                "symbol": intent.symbol,
                "action": intent.action,
                "status": intent.status,
                "qty": self._safe_float(intent.qty),
                "created_at": (
                    intent.created_at.isoformat()
                    if intent.created_at
                    else None
                ),
                "policy": policy,
                "pretrade_cost": pretrade,
                "grade": getattr(log, "grade", None),
            })
        return {
            "rows": rows,
            "total_budget": total_budget,
            "realized": realized,
            "forced": forced,
            "high_urgency": high_urgency,
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
        base_stmt = (
            select(AutonomousExecutionIntent)
            .where(AutonomousExecutionIntent.account_id.in_(keys))
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
            }

        intent_ids = [int(intent.id) for intent in intents]
        log_stmt = select(ExecutionQualityLog).where(
            ExecutionQualityLog.intent_id.in_(intent_ids)
        )
        logs = list((await db.execute(log_stmt)).scalars().all())
        logs_by_intent = {int(log.intent_id): log for log in logs}

        acc = self._accumulate_policy_rows(intents[:limit], logs_by_intent)
        policy_rows = acc["rows"]
        realized = acc["realized"]
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
                    round(sum(realized) / len(realized), 2)
                    if realized
                    else 0.0
                ),
            },
            "policies": policy_rows,
            "lookup": lookup,
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
        log = (await db.execute(log_stmt)).scalars().one_or_none()
        policy = self._derive_policy_snapshot(intent, log)
        pretrade = self._derive_pretrade_cost(intent, log)
        timeline = self._build_replay_timeline(intent, log, policy)
        exceptions = self._build_exceptions(intent, log, policy)

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
                    intent.created_at.isoformat()
                    if intent.created_at
                    else None
                ),
                "updated_at": (
                    intent.updated_at.isoformat()
                    if intent.updated_at
                    else None
                ),
            },
            "policy": policy,
            "pretrade_cost": pretrade,
            "timeline": timeline,
            "exceptions": exceptions,
            "execution_result": execution_result,
        }


execution_policy_service = ExecutionPolicyService()
