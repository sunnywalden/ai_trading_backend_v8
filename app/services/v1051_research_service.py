from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


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
        executed = sum(1 for signal in signals if str(signal.status) == "SignalStatus.EXECUTED" or str(signal.status) == "EXECUTED")
        evaluated = [signal for signal in signals if signal.actual_return is not None or signal.pnl is not None or signal.pnl_pct is not None]
        winners = [signal for signal in evaluated if cls._coerce_winner(signal) is True]
        expected_returns = [cls._safe_float(signal.expected_return) for signal in signals if signal.expected_return is not None]
        actual_returns = [cls._safe_float(signal.actual_return) for signal in evaluated if signal.actual_return is not None]
        pnl_pcts = [cls._safe_float(signal.pnl_pct) for signal in evaluated if signal.pnl_pct is not None]
        confidences = [cls._safe_float(signal.confidence) for signal in signals if signal.confidence is not None]

        return {
            "generated": generated,
            "executed": executed,
            "evaluated": len(evaluated),
            "win_rate": round(len(winners) / len(evaluated), 4) if evaluated else 0.0,
            "avg_expected_return": round(sum(expected_returns) / len(expected_returns), 4) if expected_returns else 0.0,
            "avg_actual_return": round(sum(actual_returns) / len(actual_returns), 4) if actual_returns else 0.0,
            "avg_pnl_pct": round(sum(pnl_pcts) / len(pnl_pcts), 4) if pnl_pcts else 0.0,
            "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        }

    @staticmethod
    def _compute_strategy_stage(active: bool, last_status: str | None, hit_rate: float, sample_size: int) -> str:
        status = (last_status or "").upper()
        if active and status == "SUCCESS" and sample_size >= 20 and hit_rate >= 0.55:
            return "PRODUCTION"
        if status == "SUCCESS" and sample_size >= 10:
            return "CHALLENGER"
        if sample_size > 0:
            return "PAPER"
        return "DISCOVERY"

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
        positive_weights = [item["weight"] for item in top_target if item["weight"] > 0]
        risk_budget = []
        denom = sum(weight * weight for weight in positive_weights)
        if denom > 0:
            for item in top_target:
                weight = max(item["weight"], 0.0)
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
            "avg_total_is_bps": round(sum(total_is) / len(total_is), 2) if total_is else 0.0,
            "avg_fill_rate": round(sum(fill_rates) / len(fill_rates), 4) if fill_rates else 0.0,
            "avg_time_to_fill_ms": round(sum(fill_times) / len(fill_times), 1) if fill_times else 0.0,
            "avg_quality_score": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0.0,
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
        now = datetime.utcnow()
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
            strategy_stmt = select(Strategy).where(Strategy.id.in_(sorted(set(strategy_ids))))
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
                    "avg_expected_return": summary["avg_expected_return"],
                    "avg_actual_return": summary["avg_actual_return"],
                    "alpha_gap": round(summary["avg_actual_return"] - summary["avg_expected_return"], 4),
                    "avg_confidence": summary["avg_confidence"],
                }
            )
        strategy_scorecards.sort(key=lambda item: (item["evaluated"], item["win_rate"]), reverse=True)

        recent_window = now - timedelta(days=30)
        previous_window = recent_window - timedelta(days=30)
        decay_monitor = []
        for strategy_id, bucket in by_strategy.items():
            recent_bucket = [signal for signal in bucket if signal.generated_at and signal.generated_at >= recent_window]
            previous_bucket = [
                signal
                for signal in bucket
                if signal.generated_at and previous_window <= signal.generated_at < recent_window
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
                    "win_rate_delta": round(recent_summary["win_rate"] - previous_summary["win_rate"], 4),
                    "recent_alpha_gap": round(recent_summary["avg_actual_return"] - recent_summary["avg_expected_return"], 4),
                    "previous_alpha_gap": round(previous_summary["avg_actual_return"] - previous_summary["avg_expected_return"], 4),
                    "recent_sample_size": recent_summary["evaluated"],
                    "previous_sample_size": previous_summary["evaluated"],
                }
            )
        decay_monitor.sort(key=lambda item: item["win_rate_delta"])

        regime_stmt = select(MarketRegime).order_by(desc(MarketRegime.classification_date)).limit(12)
        regimes = list((await db.execute(regime_stmt)).scalars().all())
        current_regime = regimes[0].to_dict() if regimes else None

        ghost_stmt = select(GhostTrade).order_by(desc(GhostTrade.created_at)).limit(300)
        ghost_trades = list((await db.execute(ghost_stmt)).scalars().all())
        closed_ghosts = [trade for trade in ghost_trades if str(trade.ghost_result) != "OPEN"]
        ghost_wins = sum(1 for trade in closed_ghosts if str(trade.ghost_result) == "WIN")
        rejection_buckets: dict[str, list[Any]] = defaultdict(list)
        for trade in ghost_trades:
            rejection_buckets[trade.rejection_reason or "UNKNOWN"].append(trade)
        shadow_book = {
            "total": len(ghost_trades),
            "closed": len(closed_ghosts),
            "win_rate": round(ghost_wins / len(closed_ghosts), 4) if closed_ghosts else 0.0,
            "avg_pnl_pct": round(
                sum(self._safe_float(trade.ghost_pnl_pct) for trade in closed_ghosts) / len(closed_ghosts),
                4,
            ) if closed_ghosts else 0.0,
            "rejection_breakdown": sorted(
                (
                    {
                        "reason": reason,
                        "count": len(bucket),
                        "avg_pnl_pct": round(
                            sum(self._safe_float(item.ghost_pnl_pct) for item in bucket if item.ghost_pnl_pct is not None)
                            / max(sum(1 for item in bucket if item.ghost_pnl_pct is not None), 1),
                            4,
                        ),
                    }
                    for reason, bucket in rejection_buckets.items()
                ),
                key=lambda item: item["count"],
                reverse=True,
            )[:8],
        }

        recent_signals = [
            {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "status": str(signal.status).split(".")[-1],
                "strategy_name": strategies_by_id.get(signal.strategy_id).name if signal.strategy_id in strategies_by_id else None,
                "confidence": self._safe_float(signal.confidence),
                "expected_return": self._safe_float(signal.expected_return),
                "actual_return": self._safe_float(signal.actual_return) if signal.actual_return is not None else None,
                "generated_at": signal.generated_at.isoformat() if signal.generated_at else None,
            }
            for signal in signals[:20]
        ]

        return {
            "lookback_days": lookback_days,
            "summary": overall,
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
        account_id: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        from app.models.ai_insight import ABExperiment, AIInsight
        from app.models.strategy import Strategy, StrategyRun

        strategy_stmt = select(Strategy).order_by(desc(Strategy.updated_at)).limit(max(limit, 20))
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
            sample_size = int(getattr(history, "hits", 0) or len(runs))
            stage = self._compute_strategy_stage(strategy.is_active, strategy.last_run_status, hit_rate, sample_size)
            pipeline.append(
                {
                    "strategy_id": strategy.id,
                    "name": strategy.name,
                    "style": strategy.style,
                    "version": strategy.version,
                    "is_active": strategy.is_active,
                    "last_run_status": strategy.last_run_status,
                    "last_run_at": strategy.last_run_at.isoformat() if strategy.last_run_at else None,
                    "run_count": len(runs),
                    "stage": stage,
                    "hit_rate": round(hit_rate, 4),
                    "avg_signal_strength": round(self._safe_float(getattr(history, "avg_signal_strength", 0.0)), 4),
                    "scanned_total": int(getattr(history, "scanned_total", 0) or 0),
                    "hits": int(getattr(history, "hits", 0) or 0),
                }
            )
        stage_rank = {"PRODUCTION": 4, "CHALLENGER": 3, "PAPER": 2, "DISCOVERY": 1}
        pipeline.sort(key=lambda item: (stage_rank.get(item["stage"], 0), item["run_count"]), reverse=True)

        experiments_stmt = select(ABExperiment).order_by(desc(ABExperiment.created_at)).limit(10)
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
                    "strategy_name": strategy_name_by_id.get(run.strategy_id, run.strategy_id),
                    "status": run.status,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "hit_rate": round(self._safe_float(getattr(history, "hit_rate", 0.0)), 4),
                    "avg_signal_strength": round(self._safe_float(getattr(history, "avg_signal_strength", 0.0)), 4),
                    "hits": int(getattr(history, "hits", 0) or 0),
                }
            )

        return {
            "funnel": {
                "discovery": len(pipeline),
                "paper": sum(1 for item in pipeline if item["stage"] in {"PAPER", "CHALLENGER", "PRODUCTION"}),
                "challenger": sum(1 for item in pipeline if item["stage"] in {"CHALLENGER", "PRODUCTION"}),
                "production": sum(1 for item in pipeline if item["stage"] == "PRODUCTION"),
            },
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

        construction = self._summarize_weight_shift(
            getattr(latest, "current_weights", None),
            getattr(latest, "target_weights", None),
        ) if latest else self._summarize_weight_shift({}, {})

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
                "created_at": latest.created_at.isoformat() if latest.created_at else None,
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
                    "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
                }
                for snapshot in snapshots
            ],
            "execution_quality": self._summarize_execution_logs(execution_logs),
        }


v1051_research_service = V1051ResearchService()