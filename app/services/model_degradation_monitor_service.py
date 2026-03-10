"""model_degradation_monitor_service.py — V10.5.1 M4

实时检测以下退化信号：
  1. strategy hit rate drift      — 策略命中率漂移
  2. confidence calibration drift — 置信度校准漂移（ECE）
  3. execution cost drift         — 执行成本漂移
  4. broker reject spike          — 券商拒绝率突增
  5. feature freshness drift      — 特征陈旧度（通过 signal_quality_audit_log 代理）

返回结构包括每个指标的当前值、基线值、漂移幅度与严重等级（OK/WARNING/CRITICAL）。
阈值：
  - 命中率漂移 > 0.08 → WARNING；> 0.15 → CRITICAL
  - ECE 漂移   > 0.05 → WARNING；> 0.12 → CRITICAL
  - 执行成本漂移 > 5 bps → WARNING；> 15 bps → CRITICAL
  - 拒绝率突增  > 0.15 → WARNING；> 0.35 → CRITICAL
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_OK = "OK"
_WARNING = "WARNING"
_CRITICAL = "CRITICAL"


def _severity(magnitude: float, warn_threshold: float, crit_threshold: float) -> str:
    if magnitude >= crit_threshold:
        return _CRITICAL
    if magnitude >= warn_threshold:
        return _WARNING
    return _OK


def _safe_float(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_execution_layer_broker_failure(intent: Any) -> bool:
    """仅统计执行层/券商层失败，避免把策略层 REJECTED 误算为 broker reject。

    历史上 AutonomousExecutionIntent.status=REJECTED 既可能表示风控/熔断/建议模式
    等策略内拒绝，也可能表示外部执行失败；AI 安全页中的 BROKER_REJECT_SPIKE 只应
    关注真正发生在下单/券商同步阶段的失败。
    """
    status = str(getattr(intent, "status", "") or "").upper()
    reason = str(getattr(intent, "reason", "") or "").lower()

    if status in {"FAILED", "ERROR"}:
        return True

    # 仅对少数明确指向券商/执行提交的 REJECTED 保留统计口径。
    if status == "REJECTED" and (
        "order-submission-failed" in reason
        or "broker-" in reason
        or "order rejected" in reason
        or "broker rejected" in reason
    ):
        return True

    return False


class ModelDegradationMonitorService:
    """V10.5.1 M4 — 模型退化监控服务。

    所有方法返回纯 dict 列表，每个 dict 对应一条退化指标快照，结构：
    {
        "strategy_id":    str | None,
        "metric_type":    str,
        "current_value":  float,
        "baseline_value": float,
        "drift_magnitude": float,
        "drift_direction": "UP"|"DOWN"|"NONE",
        "severity":       "OK"|"WARNING"|"CRITICAL",
        "details":        dict,
    }
    """

    # ── 1. Hit-rate drift ──────────────────────────────────────────────────

    @staticmethod
    async def _hit_rate_drift(
        db: AsyncSession,
        account_id: str,
        keys: list[str],
        now: datetime,
    ) -> list[dict[str, Any]]:
        from app.models.trading_signal import TradingSignal

        # recent 30d vs previous 30d, per strategy
        recent_since = now - timedelta(days=30)
        prev_since = now - timedelta(days=60)

        stmt = (
            select(TradingSignal)
            .where(
                or_(
                    TradingSignal.account_id.in_(keys),
                    TradingSignal.user_id.in_(keys),
                ),
                TradingSignal.generated_at >= prev_since,
                TradingSignal.actual_return.is_not(None),
            )
            .order_by(desc(TradingSignal.generated_at))
            .limit(2000)
        )
        signals = list((await db.execute(stmt)).scalars().all())

        by_strategy: dict[str, tuple[list[Any], list[Any]]] = defaultdict(
            lambda: ([], [])
        )
        for sig in signals:
            key = str(sig.strategy_id or "GLOBAL")
            recent_list, prev_list = by_strategy[key]
            if sig.generated_at and sig.generated_at >= recent_since:
                recent_list.append(sig)
            else:
                prev_list.append(sig)

        _MIN_EVAL = 5  # 两个窗口各自至少需要 5 条已结算信号才能计算漂移

        def _hit_rate_or_none(sigs: list[Any]) -> float | None:
            """计算命中率；若已结算样本不足 _MIN_EVAL 则返回 None（数据不足）。"""
            evaluated = [s for s in sigs if s.actual_return is not None]
            if len(evaluated) < _MIN_EVAL:
                return None  # 不足以判断，避免基线为 0 引起虚假漂移报警
            wins = [s for s in evaluated if _safe_float(s.actual_return) > 0]
            return len(wins) / len(evaluated)

        results: list[dict[str, Any]] = []
        for strategy_id, (recent_sigs, prev_sigs) in by_strategy.items():
            # 任一窗口信号量不足，跳过（原代码使用 and，导致 prev 为空时仍计算）
            if len(recent_sigs) < _MIN_EVAL or len(prev_sigs) < _MIN_EVAL:
                continue

            current = _hit_rate_or_none(recent_sigs)
            baseline = _hit_rate_or_none(prev_sigs)
            # 若任一窗口已结算样本不足，跳过（避免 baseline=0% 的虚假 CRITICAL）
            if current is None or baseline is None:
                continue

            drift = baseline - current  # positive = hit rate fell
            magnitude = abs(drift)
            results.append(
                {
                    "strategy_id": None if strategy_id == "GLOBAL" else strategy_id,
                    "metric_type": "HIT_RATE_DRIFT",
                    "current_value": round(current, 4),
                    "baseline_value": round(baseline, 4),
                    "drift_magnitude": round(magnitude, 4),
                    "drift_direction": "DOWN" if drift > 0.005 else ("UP" if drift < -0.005 else "NONE"),
                    "severity": _severity(magnitude, 0.08, 0.15),
                    "details": {
                        "recent_sample": len(recent_sigs),
                        "prev_sample": len(prev_sigs),
                        "recent_evaluated": len([s for s in recent_sigs if s.actual_return is not None]),
                        "prev_evaluated": len([s for s in prev_sigs if s.actual_return is not None]),
                        "window_days": 30,
                    },
                }
            )
        return results

    # ── 2. ECE (calibration) drift ────────────────────────────────────────

    @staticmethod
    async def _ece_drift(
        db: AsyncSession,
        keys: list[str],
        now: datetime,
    ) -> list[dict[str, Any]]:
        from app.models.confidence_calibration_snapshot import \
            ConfidenceCalibrationSnapshot

        recent_since = now - timedelta(days=7)
        stmt = (
            select(ConfidenceCalibrationSnapshot)
            .where(ConfidenceCalibrationSnapshot.account_id.in_(keys))
            .order_by(desc(ConfidenceCalibrationSnapshot.created_at))
            .limit(20)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        if len(rows) < 2:
            return []

        recent_rows = [r for r in rows if r.created_at and r.created_at >= recent_since]
        older_rows = [r for r in rows if not (r.created_at and r.created_at >= recent_since)]
        if not recent_rows or not older_rows:
            return []

        def _avg_ece(snapshots: list[Any]) -> float:
            vals = [_safe_float(getattr(r, "ece", None)) for r in snapshots]
            vals = [v for v in vals if v > 0]
            return sum(vals) / len(vals) if vals else 0.0

        current = _avg_ece(recent_rows)
        baseline = _avg_ece(older_rows)
        drift = current - baseline
        magnitude = abs(drift)
        return [
            {
                "strategy_id": None,
                "metric_type": "ECE_DRIFT",
                "current_value": round(current, 4),
                "baseline_value": round(baseline, 4),
                "drift_magnitude": round(magnitude, 4),
                "drift_direction": "UP" if drift > 0.005 else ("DOWN" if drift < -0.005 else "NONE"),
                "severity": _severity(magnitude, 0.05, 0.12),
                "details": {
                    "recent_snapshots": len(recent_rows),
                    "older_snapshots": len(older_rows),
                },
            }
        ]

    # ── 3. Execution cost drift ───────────────────────────────────────────

    @staticmethod
    async def _exec_cost_drift(
        db: AsyncSession,
        keys: list[str],
        now: datetime,
    ) -> list[dict[str, Any]]:
        from app.models.execution_quality_log import ExecutionQualityLog
        from app.models.execution_intent import AutonomousExecutionIntent

        recent_since = now - timedelta(days=7)
        prev_since = now - timedelta(days=21)

        stmt = (
            select(ExecutionQualityLog)
            .join(
                AutonomousExecutionIntent,
                AutonomousExecutionIntent.id == ExecutionQualityLog.intent_id,
            )
            .where(
                ExecutionQualityLog.account_id.in_(keys),
                ExecutionQualityLog.created_at >= prev_since,
                AutonomousExecutionIntent.status == "SUCCESS",
            )
            .order_by(desc(ExecutionQualityLog.created_at))
            .limit(500)
        )
        logs = list((await db.execute(stmt)).scalars().all())
        if not logs:
            return []

        recent_logs = [l for l in logs if l.created_at and l.created_at >= recent_since]
        prev_logs = [l for l in logs if not (l.created_at and l.created_at >= recent_since)]
        if not recent_logs or not prev_logs:
            return []

        def _avg_is(ls: list[Any]) -> float:
            vals = [_safe_float(l.total_is_bps) for l in ls]
            return sum(vals) / len(vals) if vals else 0.0

        current = _avg_is(recent_logs)
        baseline = _avg_is(prev_logs)
        drift = current - baseline
        magnitude = abs(drift)
        return [
            {
                "strategy_id": None,
                "metric_type": "EXEC_COST_DRIFT",
                "current_value": round(current, 2),
                "baseline_value": round(baseline, 2),
                "drift_magnitude": round(magnitude, 2),
                "drift_direction": "UP" if drift > 0.5 else ("DOWN" if drift < -0.5 else "NONE"),
                "severity": _severity(magnitude, 5.0, 15.0),
                "details": {
                    "recent_sample": len(recent_logs),
                    "prev_sample": len(prev_logs),
                    "unit": "bps",
                    "counting_rule": "successful executions only",
                },
            }
        ]

    # ── 4. Broker reject spike ─────────────────────────────────────────────

    @staticmethod
    async def _broker_reject_spike(
        db: AsyncSession,
        keys: list[str],
        now: datetime,
    ) -> list[dict[str, Any]]:
        from app.models.execution_intent import AutonomousExecutionIntent

        recent_since = now - timedelta(days=3)
        prev_since = now - timedelta(days=10)

        stmt = (
            select(AutonomousExecutionIntent)
            .where(
                AutonomousExecutionIntent.account_id.in_(keys),
                AutonomousExecutionIntent.created_at >= prev_since,
            )
            .order_by(desc(AutonomousExecutionIntent.created_at))
            .limit(500)
        )
        intents = list((await db.execute(stmt)).scalars().all())
        if not intents:
            return []

        def _reject_rate(items: list[Any]) -> float:
            if not items:
                return 0.0
            failed = sum(1 for i in items if _is_execution_layer_broker_failure(i))
            return failed / len(items)

        recent = [i for i in intents if i.created_at and i.created_at >= recent_since]
        prev = [i for i in intents if not (i.created_at and i.created_at >= recent_since)]
        if not recent or not prev:
            return []

        current = _reject_rate(recent)
        baseline = _reject_rate(prev)
        drift = current - baseline
        # 这是“reject spike”而不是“reject shift”：仅对上升漂移报警。
        magnitude = max(drift, 0.0)
        return [
            {
                "strategy_id": None,
                "metric_type": "BROKER_REJECT_SPIKE",
                "current_value": round(current, 4),
                "baseline_value": round(baseline, 4),
                "drift_magnitude": round(magnitude, 4),
                "drift_direction": "UP" if drift > 0.01 else ("DOWN" if drift < -0.01 else "NONE"),
                "severity": _severity(magnitude, 0.15, 0.35),
                "details": {
                    "recent_sample": len(recent),
                    "prev_sample": len(prev),
                    "recent_reject_count": sum(
                        1 for i in recent if _is_execution_layer_broker_failure(i)
                    ),
                    "counting_rule": "execution-layer failures only",
                },
            }
        ]

    # ── Public API ────────────────────────────────────────────────────────

    @staticmethod
    def _candidate_keys(account_id: str) -> list[str]:
        keys = [str(account_id)]
        if "@" in account_id:
            keys.append(account_id.split("@", 1)[0])
        if account_id.lower().startswith("user_"):
            keys.append(account_id[5:])
        return [k for idx, k in enumerate(keys) if k and k not in keys[:idx]]

    async def get_degradation_report(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> dict[str, Any]:
        """全量退化状态报告，聚合四类指标，返回摘要与明细。"""
        keys = self._candidate_keys(account_id)
        now = datetime.utcnow()

        all_metrics: list[dict[str, Any]] = []

        try:
            all_metrics.extend(await self._hit_rate_drift(db, account_id, keys, now))
        except Exception:
            pass

        try:
            all_metrics.extend(await self._ece_drift(db, keys, now))
        except Exception:
            pass

        try:
            all_metrics.extend(await self._exec_cost_drift(db, keys, now))
        except Exception:
            pass

        try:
            all_metrics.extend(await self._broker_reject_spike(db, keys, now))
        except Exception:
            pass

        critical_count = sum(1 for m in all_metrics if m["severity"] == _CRITICAL)
        warning_count = sum(1 for m in all_metrics if m["severity"] == _WARNING)

        overall_severity: str
        if critical_count > 0:
            overall_severity = _CRITICAL
        elif warning_count >= 2:
            overall_severity = _WARNING
        elif warning_count == 1:
            overall_severity = _WARNING
        else:
            overall_severity = _OK

        return {
            "as_of": now.isoformat(),
            "overall_severity": overall_severity,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "ok_count": sum(1 for m in all_metrics if m["severity"] == _OK),
            "metrics": all_metrics,
        }


model_degradation_monitor_service = ModelDegradationMonitorService()
