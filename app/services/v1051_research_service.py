from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


class V1051ResearchService:
    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            if value is None:
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _normalize_origin_mode(value: Any) -> str:
        text = str(value or "").strip().upper()
        if text in {"REAL", "SYNTHETIC", "BACKFILL"}:
            return text
        return "UNKNOWN"

    @classmethod
    def _extract_origin_mode(cls, signal: Any) -> str:
        meta = cls._safe_dict(getattr(signal, "extra_metadata", None))
        payload = cls._safe_dict(meta.get("signal_payload"))
        factor_scores = cls._safe_dict(getattr(signal, "factor_scores", None))
        signal_dims = cls._safe_dict(factor_scores.get("signal_dimensions"))
        for candidate in (
            getattr(signal, "signal_origin_mode", None),
            meta.get("signal_origin_mode"),
            payload.get("origin_mode"),
            factor_scores.get("signal_origin_mode"),
            signal_dims.get("signal_origin_mode"),
        ):
            normalized = cls._normalize_origin_mode(candidate)
            if normalized != "UNKNOWN":
                return normalized
        return "UNKNOWN"

    @classmethod
    def _summarize_origin_breakdown(
        cls,
        signals: list[Any],
    ) -> list[dict[str, Any]]:
        total = len(signals)
        counts: dict[str, int] = defaultdict(int)
        for signal in signals:
            counts[cls._extract_origin_mode(signal)] += 1

        ordered = ["REAL", "SYNTHETIC", "BACKFILL", "UNKNOWN"]
        return [
            {
                "mode": mode,
                "count": counts.get(mode, 0),
                "ratio": (
                    round(
                        counts.get(mode, 0) / total,
                        4,
                    )
                    if total
                    else 0.0
                ),
            }
            for mode in ordered
            if counts.get(mode, 0) > 0 or (mode == "UNKNOWN" and total == 0)
        ]

    @classmethod
    def _build_signal_integrity_summary(
        cls,
        signals: list[Any],
    ) -> dict[str, Any]:
        total = len(signals)
        canonical_payload_ready = 0
        native_transition_ready = 0
        origin_known = 0
        for signal in signals:
            meta = cls._safe_dict(getattr(signal, "extra_metadata", None))
            payload = cls._safe_dict(meta.get("signal_payload"))
            transitions = meta.get("signal_transitions")
            if payload.get("version") == "v10.5.4":
                canonical_payload_ready += 1
            if isinstance(transitions, list) and transitions:
                native_transition_ready += 1
            if cls._extract_origin_mode(signal) != "UNKNOWN":
                origin_known += 1

        def _ratio(value: int) -> float:
            return round(value / total, 4) if total else 0.0

        return {
            "sample_size": total,
            "origin_breakdown": cls._summarize_origin_breakdown(signals),
            "origin_known": origin_known,
            "origin_known_ratio": _ratio(origin_known),
            "canonical_payload_ready": canonical_payload_ready,
            "canonical_payload_ratio": _ratio(canonical_payload_ready),
            "native_transition_ready": native_transition_ready,
            "native_transition_ratio": _ratio(native_transition_ready),
        }

    @staticmethod
    def _build_rollout_state() -> dict[str, Any]:
        flags = {
            "alpha_truth_v2_enabled": bool(settings.ALPHA_TRUTH_V2_ENABLED),
            "seat_value_arbiter_enabled": bool(settings.SEAT_VALUE_ARBITER_ENABLED),
            "execution_policy_hard_control_enabled": bool(
                settings.EXECUTION_POLICY_HARD_CONTROL_ENABLED
            ),
            "governance_hard_gate_enabled": bool(settings.GOVERNANCE_HARD_GATE_ENABLED),
            "signal_pipeline_v1054_enabled": bool(
                settings.SIGNAL_PIPELINE_V1054_ENABLED
            ),
            "autonomous_control_plane_v1054_enabled": bool(
                settings.AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED
            ),
            "native_audit_v1054_enabled": bool(settings.NATIVE_AUDIT_V1054_ENABLED),
        }
        if (
            flags["signal_pipeline_v1054_enabled"]
            and flags["autonomous_control_plane_v1054_enabled"]
            and flags["native_audit_v1054_enabled"]
            and flags["governance_hard_gate_enabled"]
        ):
            stage = "FULL"
            next_step = "保持治理观测，准备全面接管"
        elif (
            flags["autonomous_control_plane_v1054_enabled"]
            and flags["native_audit_v1054_enabled"]
        ):
            stage = "SEMI"
            next_step = "验证治理硬门后进入 FULL"
        elif flags["signal_pipeline_v1054_enabled"]:
            stage = "SHADOW"
            next_step = "开启原生审计与控制面灰度"
        else:
            stage = "OBSERVE"
            next_step = "先开启 SIGNAL_PIPELINE_V1054_ENABLED"

        return {
            "stage": stage,
            "flags": flags,
            "recommended_next_step": next_step,
        }

    @classmethod
    def _extract_turnover_penalty(cls, signal: Any) -> float:
        meta = cls._safe_dict(getattr(signal, "extra_metadata", None))
        for key in (
            "turnover_penalty_pct",
            "turnover_cost_pct",
            "estimated_turnover_cost",
            "after_turnover_penalty",
        ):
            if key in meta:
                return abs(cls._safe_float(meta.get(key)))
        return 0.0

    @classmethod
    def _extract_regime_bucket(cls, signal: Any) -> str:
        meta = cls._safe_dict(getattr(signal, "extra_metadata", None))
        regime = (
            meta.get("market_regime")
            or meta.get("regime")
            or meta.get("regime_at_decision")
        )
        return str(regime or "UNKNOWN").upper()

    @classmethod
    def _extract_capacity_bucket(cls, signal: Any) -> str:
        meta = cls._safe_dict(getattr(signal, "extra_metadata", None))
        adv_usd = cls._safe_float(meta.get("adv_usd"))
        market_cap = cls._safe_float(meta.get("market_cap"))
        liquidity_proxy = max(
            adv_usd,
            market_cap / 250 if market_cap > 0 else 0.0,
        )
        if liquidity_proxy >= 50_000_000:
            return "XL"
        if liquidity_proxy >= 10_000_000:
            return "L"
        if liquidity_proxy >= 1_000_000:
            return "M"
        if liquidity_proxy > 0:
            return "S"
        return "UNKNOWN"

    @classmethod
    def _infer_data_quality(
        cls,
        signals: list[Any],
        evaluated_count: int,
    ) -> str:
        if not signals:
            return "INSUFFICIENT"
        latest_generated = max(
            (
                signal.generated_at
                for signal in signals
                if getattr(signal, "generated_at", None)
            ),
            default=None,
        )
        if evaluated_count == 0:
            return "PROXY"
        if evaluated_count < 5:
            return "INSUFFICIENT"
        if latest_generated and latest_generated < datetime.now() - timedelta(
            days=21,
        ):
            return "STALE"
        return "REAL"

    @classmethod
    def _summarize_bucket_breakdown(
        cls,
        signals: list[Any],
        extractor: Any,
    ) -> list[dict[str, Any]]:
        buckets: dict[str, list[Any]] = defaultdict(list)
        for signal in signals:
            buckets[extractor(signal)].append(signal)
        ranked = []
        for bucket_name, bucket_signals in buckets.items():
            actual_returns = [
                cls._safe_float(signal.actual_return)
                for signal in bucket_signals
                if signal.actual_return is not None
            ]
            ranked.append(
                {
                    "bucket": bucket_name,
                    "count": len(bucket_signals),
                    "avg_actual_return": (
                        round(sum(actual_returns) / len(actual_returns), 4)
                        if actual_returns
                        else 0.0
                    ),
                }
            )
        ranked.sort(key=lambda item: item["count"], reverse=True)
        return ranked

    @staticmethod
    def _candidate_keys(account_id: str) -> list[str]:
        keys = [str(account_id)]
        if "@" in account_id:
            keys.append(account_id.split("@", 1)[0])
        if account_id.lower().startswith("user_"):
            keys.append(account_id[5:])
        return [key for idx, key in enumerate(keys) if key and key not in keys[:idx]]

    @staticmethod
    def _coerce_winner(signal: Any) -> bool | None:
        if signal.is_winner == "YES":
            return True
        if signal.is_winner == "NO":
            return False
        if signal.actual_return is not None:
            return float(signal.actual_return) > 0
        if signal.pnl is not None:
            return float(signal.pnl) > 0
        if signal.pnl_pct is not None:
            return float(signal.pnl_pct) > 0
        return None

    @classmethod
    def _summarize_signal_bucket(cls, signals: list[Any]) -> dict[str, Any]:
        generated = len(signals)
        executed = sum(
            1
            for signal in signals
            if str(signal.status) == "SignalStatus.EXECUTED"
            or str(signal.status) == "EXECUTED"
        )
        evaluated = [
            signal
            for signal in signals
            if signal.actual_return is not None
            or signal.pnl is not None
            or signal.pnl_pct is not None
        ]
        winners = [signal for signal in evaluated if cls._coerce_winner(signal) is True]
        expected_returns = [
            cls._safe_float(signal.expected_return)
            for signal in signals
            if signal.expected_return is not None
        ]
        actual_returns = [
            cls._safe_float(signal.actual_return)
            for signal in evaluated
            if signal.actual_return is not None
        ]
        pnl_pcts = [
            cls._safe_float(signal.pnl_pct)
            for signal in evaluated
            if signal.pnl_pct is not None
        ]
        confidences = [
            cls._safe_float(signal.confidence)
            for signal in signals
            if signal.confidence is not None
        ]
        execution_slippages = [
            abs(cls._safe_float(signal.execution_slippage))
            for signal in evaluated
            if getattr(signal, "execution_slippage", None) is not None
        ]
        turnover_penalties = [
            cls._extract_turnover_penalty(signal)
            for signal in signals
            if cls._extract_turnover_penalty(signal) > 0
        ]

        gross_return = (
            round(sum(expected_returns) / len(expected_returns), 4)
            if expected_returns
            else 0.0
        )
        net_return = (
            round(sum(actual_returns) / len(actual_returns), 4)
            if actual_returns
            else 0.0
        )
        avg_execution_slippage = (
            round(sum(execution_slippages) / len(execution_slippages), 4)
            if execution_slippages
            else 0.0
        )
        after_cost_return = round(net_return - avg_execution_slippage, 4)
        if pnl_pcts:
            after_turnover_return = round(sum(pnl_pcts) / len(pnl_pcts), 4)
        else:
            turnover_penalty = (
                sum(turnover_penalties) / len(turnover_penalties)
                if turnover_penalties
                else 0.0
            )
            after_turnover_return = round(
                after_cost_return - turnover_penalty,
                4,
            )
        data_quality = cls._infer_data_quality(signals, len(evaluated))

        return {
            "generated": generated,
            "executed": executed,
            "evaluated": len(evaluated),
            "win_rate": (round(len(winners) / len(evaluated), 4) if evaluated else 0.0),
            "gross_return": gross_return,
            "net_return": net_return,
            "after_cost_return": after_cost_return,
            "after_turnover_return": after_turnover_return,
            "data_quality": data_quality,
            "avg_execution_slippage": avg_execution_slippage,
            "avg_expected_return": gross_return,
            "avg_actual_return": net_return,
            "avg_pnl_pct": (
                round(sum(pnl_pcts) / len(pnl_pcts), 4) if pnl_pcts else 0.0
            ),
            "avg_confidence": (
                round(sum(confidences) / len(confidences), 4) if confidences else 0.0
            ),
            "origin_breakdown": cls._summarize_origin_breakdown(signals),
            "regime_breakdown": cls._summarize_bucket_breakdown(
                signals,
                cls._extract_regime_bucket,
            )[:6],
            "capacity_breakdown": cls._summarize_bucket_breakdown(
                signals,
                cls._extract_capacity_bucket,
            )[:6],
        }

    @classmethod
    def _summarize_shadow_book(cls, ghost_trades: list[Any]) -> dict[str, Any]:
        closed_ghosts = [
            trade for trade in ghost_trades if str(trade.ghost_result) != "OPEN"
        ]
        ghost_wins = [
            trade for trade in closed_ghosts if str(trade.ghost_result) == "WIN"
        ]
        rejection_buckets: dict[str, list[Any]] = defaultdict(list)
        for trade in ghost_trades:
            rejection_buckets[trade.rejection_reason or "UNKNOWN"].append(trade)

        positive_pnls = [
            max(cls._safe_float(trade.ghost_pnl_pct), 0.0)
            for trade in closed_ghosts
            if cls._safe_float(trade.ghost_pnl_pct) > 0
        ]
        negative_pnls = [
            abs(min(cls._safe_float(trade.ghost_pnl_pct), 0.0))
            for trade in closed_ghosts
            if cls._safe_float(trade.ghost_pnl_pct) < 0
        ]
        missed_alpha_pct = (
            round(sum(positive_pnls) / len(positive_pnls), 4) if positive_pnls else 0.0
        )
        avoided_loss_pct = (
            round(sum(negative_pnls) / len(negative_pnls), 4) if negative_pnls else 0.0
        )
        return {
            "total": len(ghost_trades),
            "closed": len(closed_ghosts),
            "win_rate": (
                round(len(ghost_wins) / len(closed_ghosts), 4) if closed_ghosts else 0.0
            ),
            "false_reject_rate": (
                round(len(ghost_wins) / len(closed_ghosts), 4) if closed_ghosts else 0.0
            ),
            "missed_alpha_pct": missed_alpha_pct,
            "avoided_loss_pct": avoided_loss_pct,
            "protection_benefit_pct": round(
                avoided_loss_pct - missed_alpha_pct,
                4,
            ),
            "avg_pnl_pct": (
                round(
                    sum(cls._safe_float(trade.ghost_pnl_pct) for trade in closed_ghosts)
                    / len(closed_ghosts),
                    4,
                )
                if closed_ghosts
                else 0.0
            ),
            "rejection_breakdown": sorted(
                (
                    {
                        "reason": reason,
                        "count": len(bucket),
                        "avg_pnl_pct": round(
                            sum(
                                cls._safe_float(item.ghost_pnl_pct)
                                for item in bucket
                                if item.ghost_pnl_pct is not None
                            )
                            / max(
                                sum(
                                    1
                                    for item in bucket
                                    if item.ghost_pnl_pct is not None
                                ),
                                1,
                            ),
                            4,
                        ),
                    }
                    for reason, bucket in rejection_buckets.items()
                ),
                key=lambda item: item["count"],
                reverse=True,
            )[:8],
        }

    @staticmethod
    def _compute_strategy_stage(
        active: bool,
        last_status: str | None,
        hit_rate: float,
        sample_size: int,
    ) -> str:
        status = (last_status or "").upper()
        if active and status == "SUCCESS" and sample_size >= 20 and hit_rate >= 0.55:
            return "PRODUCTION"
        if status == "SUCCESS" and sample_size >= 10:
            return "CHALLENGER"
        if sample_size > 0:
            return "PAPER"
        return "DISCOVERY"

    @staticmethod
    def _compute_governance_stage(
        active: bool,
        last_status: str | None,
        hit_rate: float,
        sample_size: int,
    ) -> str:
        status = (last_status or "").upper()
        if active and status == "SUCCESS" and sample_size >= 30 and hit_rate >= 0.58:
            return "PRODUCTION"
        if status == "SUCCESS" and sample_size >= 20 and hit_rate >= 0.55:
            return "CHALLENGER"
        if sample_size >= 10 and hit_rate >= 0.50:
            return "SHADOW_LIVE"
        if sample_size > 0:
            return "PAPER"
        return "DISCOVERY"

    @classmethod
    def _build_governance_evidence(
        cls,
        *,
        active: bool,
        last_status: str | None,
        sample_size: int,
        hit_rate: float,
        avg_signal_strength: float,
    ) -> dict[str, bool]:
        status = (last_status or "").upper()
        return {
            "backtest": sample_size > 0,
            "paper": sample_size >= 1,
            "shadow": sample_size >= 10 and hit_rate >= 0.50,
            "execution": status == "SUCCESS",
            "calibration": avg_signal_strength > 0,
            "rollback_ready": active or sample_size >= 10,
        }

    @staticmethod
    def _build_governance_blockers(
        evidence_chain: dict[str, bool],
        hit_rate: float,
        last_status: str | None,
    ) -> list[str]:
        blockers: list[str] = []
        if not evidence_chain["backtest"]:
            blockers.append("BACKTEST_EVIDENCE_MISSING")
        if not evidence_chain["shadow"]:
            blockers.append("SHADOW_LIVE_EVIDENCE_MISSING")
        if (last_status or "").upper() != "SUCCESS":
            blockers.append("LATEST_RUN_NOT_SUCCESS")
        if hit_rate < 0.55:
            blockers.append("HIT_RATE_BELOW_PROMOTION_THRESHOLD")
        return blockers

    @staticmethod
    def _build_rollback_suggestion(stage: str, blockers: list[str]) -> str:
        if not blockers:
            return "HOLD_CURRENT_STAGE"
        if stage == "PRODUCTION":
            return "DOWNGRADE_TO_CHALLENGER"
        if stage == "CHALLENGER":
            return "ROLLBACK_TO_SHADOW_LIVE"
        if stage == "SHADOW_LIVE":
            return "ROLLBACK_TO_PAPER"
        return "REMAIN_IN_DISCOVERY"

    @classmethod
    def _summarize_weight_shift(
        cls,
        current_weights: dict[str, Any] | None,
        target_weights: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_weights = current_weights or {}
        target_weights = target_weights or {}
        symbols = sorted(set(current_weights) | set(target_weights))
        drifts: list[dict[str, Any]] = []
        concentration = 0.0
        total_target = 0.0

        for symbol in symbols:
            current = cls._safe_float(current_weights.get(symbol))
            target = cls._safe_float(target_weights.get(symbol))
            drift = round(target - current, 4)
            total_target += max(target, 0.0)
            concentration += max(target, 0.0) ** 2
            drifts.append(
                {
                    "symbol": symbol,
                    "current": round(current, 4),
                    "target": round(target, 4),
                    "drift": drift,
                    "abs_drift": abs(drift),
                }
            )

        drifts.sort(key=lambda item: item["abs_drift"], reverse=True)
        top_target = sorted(
            (
                {
                    "symbol": symbol,
                    "weight": round(cls._safe_float(target_weights.get(symbol)), 4),
                }
                for symbol in target_weights
            ),
            key=lambda item: item["weight"],
            reverse=True,
        )
        positive_weights = [
            cls._safe_float(item["weight"])
            for item in top_target
            if cls._safe_float(item["weight"]) > 0
        ]
        risk_budget = []
        denom = sum(weight * weight for weight in positive_weights)
        if denom > 0:
            for item in top_target:
                weight = max(cls._safe_float(item["weight"]), 0.0)
                if weight <= 0:
                    continue
                risk_budget.append(
                    {
                        "symbol": item["symbol"],
                        "budget": round((weight * weight) / denom, 4),
                    }
                )

        turnover = sum(item["abs_drift"] for item in drifts) / 2
        effective_names = round(1 / concentration, 2) if concentration > 0 else 0.0

        return {
            "turnover": round(turnover, 4),
            "gross_exposure": round(total_target, 4),
            "concentration_hhi": round(concentration, 4),
            "effective_names": effective_names,
            "top_weights": top_target[:8],
            "largest_rebalances": drifts[:8],
            "risk_budget": risk_budget[:8],
        }

    @classmethod
    def _summarize_execution_logs(cls, logs: list[Any]) -> dict[str, Any]:
        if not logs:
            return {
                "sample_size": 0,
                "avg_total_is_bps": 0.0,
                "avg_fill_rate": 0.0,
                "avg_time_to_fill_ms": 0.0,
                "avg_quality_score": 0.0,
                "worst_symbols": [],
            }

        symbol_costs: dict[str, list[float]] = defaultdict(list)
        total_is = []
        fill_rates = []
        fill_times = []
        quality_scores = []
        for log in logs:
            total = cls._safe_float(log.total_is_bps)
            total_is.append(total)
            if log.fill_rate is not None:
                fill_rates.append(cls._safe_float(log.fill_rate))
            if log.time_to_fill_ms is not None:
                fill_times.append(cls._safe_float(log.time_to_fill_ms))
            if log.quality_score is not None:
                quality_scores.append(cls._safe_float(log.quality_score))
            symbol_costs[str(log.symbol)].append(total)

        worst_symbols = sorted(
            (
                {
                    "symbol": symbol,
                    "avg_total_is_bps": round(sum(values) / len(values), 2),
                    "sample_size": len(values),
                }
                for symbol, values in symbol_costs.items()
            ),
            key=lambda item: item["avg_total_is_bps"],
            reverse=True,
        )[:5]

        return {
            "sample_size": len(logs),
            "avg_total_is_bps": (
                round(sum(total_is) / len(total_is), 2) if total_is else 0.0
            ),
            "avg_fill_rate": (
                round(sum(fill_rates) / len(fill_rates), 4) if fill_rates else 0.0
            ),
            "avg_time_to_fill_ms": (
                round(sum(fill_times) / len(fill_times), 1) if fill_times else 0.0
            ),
            "avg_quality_score": (
                round(sum(quality_scores) / len(quality_scores), 2)
                if quality_scores
                else 0.0
            ),
            "worst_symbols": worst_symbols,
        }

    async def get_alpha_lab_snapshot(
        self,
        db: AsyncSession,
        account_id: str,
        lookback_days: int = 90,
    ) -> dict[str, Any]:
        from app.models.ghost_trade import GhostTrade
        from app.models.market_regime import MarketRegime
        from app.models.strategy import Strategy
        from app.models.trading_signal import TradingSignal

        keys = self._candidate_keys(account_id)
        now = datetime.now()
        since = now - timedelta(days=max(lookback_days, 7))

        signal_stmt = (
            select(TradingSignal)
            .where(
                or_(
                    TradingSignal.account_id.in_(keys),
                    TradingSignal.user_id.in_(keys),
                ),
                TradingSignal.generated_at >= since,
            )
            .order_by(desc(TradingSignal.generated_at))
            .limit(800)
        )
        signals = list((await db.execute(signal_stmt)).scalars().all())

        strategy_ids = [signal.strategy_id for signal in signals if signal.strategy_id]
        strategies_by_id: dict[str, Any] = {}
        if strategy_ids:
            strategy_stmt = select(Strategy).where(
                Strategy.id.in_(sorted(set(strategy_ids)))
            )
            strategies = (await db.execute(strategy_stmt)).scalars().all()
            strategies_by_id = {strategy.id: strategy for strategy in strategies}

        overall = self._summarize_signal_bucket(signals)

        by_strategy: dict[str, list[Any]] = defaultdict(list)
        for signal in signals:
            strategy_key = signal.strategy_id or "UNASSIGNED"
            by_strategy[strategy_key].append(signal)

        strategy_scorecards = []
        for strategy_id, bucket in by_strategy.items():
            summary = self._summarize_signal_bucket(bucket)
            strategy = strategies_by_id.get(strategy_id)
            strategy_scorecards.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy.name if strategy else strategy_id,
                    "style": getattr(strategy, "style", None),
                    "generated": summary["generated"],
                    "evaluated": summary["evaluated"],
                    "win_rate": summary["win_rate"],
                    "gross_return": summary["gross_return"],
                    "net_return": summary["net_return"],
                    "after_cost_return": summary["after_cost_return"],
                    "after_turnover_return": summary["after_turnover_return"],
                    "data_quality": summary["data_quality"],
                    "avg_expected_return": summary["avg_expected_return"],
                    "avg_actual_return": summary["avg_actual_return"],
                    "alpha_gap": round(
                        summary["avg_actual_return"] - summary["avg_expected_return"],
                        4,
                    ),
                    "avg_confidence": summary["avg_confidence"],
                    "origin_breakdown": summary["origin_breakdown"],
                    "regime_breakdown": summary["regime_breakdown"],
                    "capacity_breakdown": summary["capacity_breakdown"],
                }
            )
        strategy_scorecards.sort(
            key=lambda item: (item["evaluated"], item["win_rate"]),
            reverse=True,
        )

        recent_window = now - timedelta(days=30)
        previous_window = recent_window - timedelta(days=30)
        decay_monitor = []
        for strategy_id, bucket in by_strategy.items():
            recent_bucket = [
                signal
                for signal in bucket
                if signal.generated_at and signal.generated_at >= recent_window
            ]
            previous_bucket = [
                signal
                for signal in bucket
                if signal.generated_at
                and previous_window <= signal.generated_at < recent_window
            ]
            recent_summary = self._summarize_signal_bucket(recent_bucket)
            previous_summary = self._summarize_signal_bucket(previous_bucket)
            if recent_summary["evaluated"] == 0 and previous_summary["evaluated"] == 0:
                continue
            strategy = strategies_by_id.get(strategy_id)
            decay_monitor.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy.name if strategy else strategy_id,
                    "recent_win_rate": recent_summary["win_rate"],
                    "previous_win_rate": previous_summary["win_rate"],
                    "win_rate_delta": round(
                        recent_summary["win_rate"] - previous_summary["win_rate"],
                        4,
                    ),
                    "recent_alpha_gap": round(
                        recent_summary["avg_actual_return"]
                        - recent_summary["avg_expected_return"],
                        4,
                    ),
                    "previous_alpha_gap": round(
                        previous_summary["avg_actual_return"]
                        - previous_summary["avg_expected_return"],
                        4,
                    ),
                    "recent_sample_size": recent_summary["evaluated"],
                    "previous_sample_size": previous_summary["evaluated"],
                    "data_quality": recent_summary["data_quality"],
                }
            )
        decay_monitor.sort(key=lambda item: item["win_rate_delta"])

        regime_stmt = (
            select(MarketRegime)
            .order_by(desc(MarketRegime.classification_date))
            .limit(12)
        )
        regimes = list((await db.execute(regime_stmt)).scalars().all())
        current_regime = regimes[0].to_dict() if regimes else None

        ghost_stmt = select(GhostTrade).order_by(desc(GhostTrade.created_at)).limit(300)
        ghost_trades = list((await db.execute(ghost_stmt)).scalars().all())
        shadow_book = self._summarize_shadow_book(ghost_trades)

        recent_signals = [
            {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "status": str(signal.status).split(".")[-1],
                "strategy_name": (
                    strategies_by_id[signal.strategy_id].name
                    if signal.strategy_id in strategies_by_id
                    else None
                ),
                "confidence": self._safe_float(signal.confidence),
                "expected_return": self._safe_float(signal.expected_return),
                "actual_return": (
                    self._safe_float(signal.actual_return)
                    if signal.actual_return is not None
                    else None
                ),
                "origin_mode": self._extract_origin_mode(signal),
                "signal_payload_version": self._safe_dict(
                    self._safe_dict(signal.extra_metadata).get("signal_payload")
                ).get("version"),
                "signal_transition_count": len(
                    self._safe_dict(signal.extra_metadata).get("signal_transitions")
                    or []
                ),
                "data_quality": self._infer_data_quality(
                    [signal],
                    (
                        1
                        if signal.actual_return is not None
                        or signal.pnl is not None
                        or signal.pnl_pct is not None
                        else 0
                    ),
                ),
                "generated_at": (
                    signal.generated_at.isoformat() if signal.generated_at else None
                ),
            }
            for signal in signals[:20]
        ]

        return {
            "lookback_days": lookback_days,
            "summary": overall,
            "origin_breakdown": overall["origin_breakdown"],
            "signal_integrity": self._build_signal_integrity_summary(signals),
            "rollout": self._build_rollout_state(),
            "current_regime": current_regime,
            "regime_tape": [regime.to_dict() for regime in regimes],
            "strategy_scorecards": strategy_scorecards[:10],
            "decay_monitor": decay_monitor[:10],
            "shadow_book": shadow_book,
            "recent_signals": recent_signals,
        }

    async def get_governance_pipeline_snapshot(
        self,
        db: AsyncSession,
        _account_id: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        from app.models.ai_insight import ABExperiment, AIInsight
        from app.models.strategy import Strategy, StrategyRun

        strategy_stmt = (
            select(Strategy).order_by(desc(Strategy.updated_at)).limit(max(limit, 20))
        )
        strategies = list((await db.execute(strategy_stmt)).scalars().all())
        strategy_ids = [strategy.id for strategy in strategies]

        runs_by_strategy: dict[str, list[Any]] = defaultdict(list)
        if strategy_ids:
            run_stmt = (
                select(StrategyRun)
                .where(StrategyRun.strategy_id.in_(strategy_ids))
                .order_by(desc(StrategyRun.created_at))
                .limit(max(limit * 8, 50))
            )
            runs = list((await db.execute(run_stmt)).scalars().all())
            for run in runs:
                runs_by_strategy[str(run.strategy_id)].append(run)

        pipeline = []
        for strategy in strategies:
            runs = runs_by_strategy.get(strategy.id, [])
            latest_run = runs[0] if runs else None
            history = latest_run.history if latest_run else None
            hit_rate = self._safe_float(getattr(history, "hit_rate", 0.0))
            avg_signal_strength = self._safe_float(
                getattr(history, "avg_signal_strength", 0.0)
            )
            sample_size = int(getattr(history, "hits", 0) or len(runs))
            stage = self._compute_governance_stage(
                strategy.is_active,
                strategy.last_run_status,
                hit_rate,
                sample_size,
            )
            evidence_chain = self._build_governance_evidence(
                active=strategy.is_active,
                last_status=strategy.last_run_status,
                sample_size=sample_size,
                hit_rate=hit_rate,
                avg_signal_strength=avg_signal_strength,
            )
            blockers = self._build_governance_blockers(
                evidence_chain,
                hit_rate,
                strategy.last_run_status,
            )
            pipeline.append(
                {
                    "strategy_id": strategy.id,
                    "name": strategy.name,
                    "style": strategy.style,
                    "version": strategy.version,
                    "is_active": strategy.is_active,
                    "last_run_status": strategy.last_run_status,
                    "last_run_at": (
                        strategy.last_run_at.isoformat()
                        if strategy.last_run_at
                        else None
                    ),
                    "run_count": len(runs),
                    "stage": stage,
                    "evidence_chain": evidence_chain,
                    "promotion_blockers": blockers,
                    "rollback_suggestion": self._build_rollback_suggestion(
                        stage,
                        blockers,
                    ),
                    "hard_gate_ready": (
                        stage in {"CHALLENGER", "PRODUCTION"} and not blockers
                    ),
                    "hit_rate": round(hit_rate, 4),
                    "avg_signal_strength": round(avg_signal_strength, 4),
                    "scanned_total": int(getattr(history, "scanned_total", 0) or 0),
                    "hits": int(getattr(history, "hits", 0) or 0),
                }
            )
        stage_rank = {
            "PRODUCTION": 5,
            "CHALLENGER": 4,
            "SHADOW_LIVE": 3,
            "PAPER": 2,
            "DISCOVERY": 1,
        }
        pipeline.sort(
            key=lambda item: (stage_rank.get(item["stage"], 0), item["run_count"]),
            reverse=True,
        )

        experiments_stmt = (
            select(ABExperiment).order_by(desc(ABExperiment.created_at)).limit(10)
        )
        experiments = list((await db.execute(experiments_stmt)).scalars().all())

        insight_stmt = select(AIInsight).order_by(desc(AIInsight.created_at)).limit(10)
        insights = list((await db.execute(insight_stmt)).scalars().all())

        recent_runs = []
        all_runs = sorted(
            [run for bucket in runs_by_strategy.values() for run in bucket],
            key=lambda run: run.created_at or datetime.min,
            reverse=True,
        )[:10]
        strategy_name_by_id = {strategy.id: strategy.name for strategy in strategies}
        for run in all_runs:
            history = run.history
            recent_runs.append(
                {
                    "run_id": run.id,
                    "strategy_id": run.strategy_id,
                    "strategy_name": strategy_name_by_id.get(
                        run.strategy_id, run.strategy_id
                    ),
                    "status": run.status,
                    "created_at": (
                        run.created_at.isoformat() if run.created_at else None
                    ),
                    "finished_at": (
                        run.finished_at.isoformat() if run.finished_at else None
                    ),
                    "hit_rate": round(
                        self._safe_float(getattr(history, "hit_rate", 0.0)), 4
                    ),
                    "avg_signal_strength": round(
                        self._safe_float(getattr(history, "avg_signal_strength", 0.0)),
                        4,
                    ),
                    "hits": int(getattr(history, "hits", 0) or 0),
                }
            )

        return {
            "rollout": self._build_rollout_state(),
            "funnel": {
                "discovery": len(pipeline),
                "paper": sum(
                    1
                    for item in pipeline
                    if item["stage"]
                    in {"PAPER", "SHADOW_LIVE", "CHALLENGER", "PRODUCTION"}
                ),
                "shadow_live": sum(
                    1
                    for item in pipeline
                    if item["stage"] in {"SHADOW_LIVE", "CHALLENGER", "PRODUCTION"}
                ),
                "challenger": sum(
                    1
                    for item in pipeline
                    if item["stage"] in {"CHALLENGER", "PRODUCTION"}
                ),
                "production": sum(
                    1 for item in pipeline if item["stage"] == "PRODUCTION"
                ),
            },
            "hard_gate_candidates": sum(
                1 for item in pipeline if item["hard_gate_ready"]
            ),
            "pipeline": pipeline[:limit],
            "experiments": [experiment.to_dict() for experiment in experiments],
            "insight_summary": {
                "total": len(insights),
                "validated": sum(1 for insight in insights if insight.validated),
                "active": sum(1 for insight in insights if insight.active),
            },
            "recent_insights": [insight.to_dict() for insight in insights],
            "recent_runs": recent_runs,
        }

    async def get_portfolio_construction_snapshot(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> dict[str, Any]:
        from app.models.execution_quality_log import ExecutionQualityLog
        from app.models.portfolio_snapshot import PortfolioSnapshot

        keys = self._candidate_keys(account_id)
        snapshot_stmt = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id.in_(keys))
            .order_by(desc(PortfolioSnapshot.created_at))
            .limit(6)
        )
        snapshots = list((await db.execute(snapshot_stmt)).scalars().all())
        latest = snapshots[0] if snapshots else None

        execution_stmt = (
            select(ExecutionQualityLog)
            .where(ExecutionQualityLog.account_id.in_(keys))
            .order_by(desc(ExecutionQualityLog.created_at))
            .limit(100)
        )
        execution_logs = list((await db.execute(execution_stmt)).scalars().all())

        construction = (
            self._summarize_weight_shift(
                getattr(latest, "current_weights", None),
                getattr(latest, "target_weights", None),
            )
            if latest
            else self._summarize_weight_shift({}, {})
        )

        latest_snapshot = None
        if latest:
            latest_snapshot = {
                "id": latest.id,
                "method": latest.method,
                "current_weights": latest.current_weights,
                "target_weights": latest.target_weights,
                "frontier": latest.frontier_data,
                "metrics": {
                    "expected_return": self._safe_float(latest.expected_return),
                    "volatility": self._safe_float(latest.expected_volatility),
                    "sharpe": self._safe_float(latest.sharpe_ratio),
                },
                "created_at": (
                    latest.created_at.isoformat() if latest.created_at else None
                ),
            }

        return {
            "latest_snapshot": latest_snapshot,
            "construction": construction,
            "history": [
                {
                    "id": snapshot.id,
                    "method": snapshot.method,
                    "metrics": {
                        "expected_return": self._safe_float(snapshot.expected_return),
                        "volatility": self._safe_float(snapshot.expected_volatility),
                        "sharpe": self._safe_float(snapshot.sharpe_ratio),
                    },
                    "target_weights": snapshot.target_weights,
                    "created_at": (
                        snapshot.created_at.isoformat() if snapshot.created_at else None
                    ),
                }
                for snapshot in snapshots
            ],
            "execution_quality": self._summarize_execution_logs(execution_logs),
        }


v1051_research_service = V1051ResearchService()
