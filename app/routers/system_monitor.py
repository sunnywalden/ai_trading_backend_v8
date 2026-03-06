"""V10.4.3: System Monitor API Router.

聚合真实数据库与现有监控服务，避免系统监控再凭空“脑补” WARN / CRITICAL。
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session, redis_client
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.trading_plan import TradingPlan
from app.routers.api_monitoring import monitoring_health_check
from app.schemas.lifecycle import PIPELINE_P50_BENCHMARKS, PIPELINE_STAGE_NAMES
from app.schemas.system_monitor import (
    DataFlowDetailResponse,
    DataFlowFailureSample,
    DataFlowNodeStatus,
    DataFlowOverviewResponse,
    DataFlowSummary,
    LifecycleExceptionItem,
    LifecycleFsmStateMetric,
    LifecycleHeadlineMetrics,
    LifecycleIntentDetailResponse,
    LifecycleOverviewResponse,
    LifecycleStageMetric,
    LifecycleTimelineEvent,
    MonitorResponseMeta,
    ServiceDetailResponse,
    ServiceHealthItem,
    ServiceHealthTimelineEvent,
    ServiceModuleSummary,
    ServiceOverviewResponse,
)
from app.services.api_monitoring_service import api_monitor
from app.services.autonomy_health_monitor import autonomy_health_monitor
from app.services.lifecycle_service import lifecycle_service
from app.services.situational_awareness_service import situational_awareness_service

router = APIRouter(prefix="/api/v1/system-monitor", tags=["V10.4.3 System Monitor"])

_STAGE_DEFAULT_THRESHOLDS: dict[int, tuple[float, float]] = {
    9: (6 * 3600.0, 24 * 3600.0),
    16: (12 * 3600.0, 48 * 3600.0),
}
_SERVICE_MODULE_LABELS = {
    "autonomy": "Autonomy",
    "infrastructure": "Infrastructure",
    "market_data": "Market Data",
    "observability": "Observability",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _meta(window_minutes: int) -> MonitorResponseMeta:
    return MonitorResponseMeta(
        generated_at=_now(),
        window_minutes=window_minutes,
        source="system-monitor-live",
        refresh_interval_seconds=30,
    )


def _to_utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stage_key(stage_id: int, stage_label: str | None = None) -> str:
    label = stage_label or PIPELINE_STAGE_NAMES.get(stage_id, f"stage_{stage_id}")
    return label.lower().replace(" ", "_").replace("/", "_")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _quantile(values: Sequence[float], q: float) -> float | None:
    cleaned = sorted(v for v in values if v is not None)
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    position = (len(cleaned) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return cleaned[low]
    weight = position - low
    return cleaned[low] * (1 - weight) + cleaned[high] * weight


def _status_from_counts(warn_count: int = 0, critical_count: int = 0, unknown: bool = False) -> str:
    if critical_count > 0:
        return "CRITICAL"
    if warn_count > 0:
        return "WARN"
    if unknown:
        return "UNKNOWN"
    return "HEALTHY"


def _stage_thresholds(stage_id: int) -> tuple[float | None, float | None]:
    p50 = PIPELINE_P50_BENCHMARKS.get(stage_id)
    if p50 is not None:
        return float(p50) * 1.5, float(p50) * 3
    return _STAGE_DEFAULT_THRESHOLDS.get(stage_id, (30 * 60.0, 2 * 3600.0))


def _classify_stage_seconds(stage_id: int, seconds: float | None) -> str:
    if seconds is None:
        return "HEALTHY"
    warn_after, critical_after = _stage_thresholds(stage_id)
    if critical_after is not None and seconds >= critical_after:
        return "CRITICAL"
    if warn_after is not None and seconds >= warn_after:
        return "WARN"
    return "HEALTHY"


def _build_exception_from_plan(plan: TradingPlan, severity: str, last_error_message: str | None = None) -> LifecycleExceptionItem:
    stage_id = int(plan.pipeline_stage or 0)
    stage_label = PIPELINE_STAGE_NAMES.get(stage_id, f"阶段 {stage_id}")
    entered_at = _to_utc(plan.stage_entered_at)
    stayed_seconds = int((_now() - entered_at).total_seconds()) if entered_at else 0
    snapshot = plan.provenance_snapshot or {}
    exec_progress = snapshot.get("exec_progress") or {}
    last_error_code = None
    if plan.plan_status == "FAILED":
        last_error_code = "PLAN_FAILED"
    elif severity == "CRITICAL":
        last_error_code = "PIPELINE_STUCK"
    return LifecycleExceptionItem(
        intent_id=plan.id,
        plan_id=plan.id,
        symbol=plan.symbol,
        action=plan.direction,
        signal_type=(plan.plan_tags or {}).get("signal_type") if isinstance(plan.plan_tags, dict) else None,
        current_stage_id=stage_id,
        current_stage_key=_stage_key(stage_id, stage_label),
        current_stage_label=stage_label,
        stayed_seconds=stayed_seconds,
        severity="critical" if severity == "CRITICAL" else "warning",
        execution_path=(plan.plan_tags or {}).get("algo_type") if isinstance(plan.plan_tags, dict) else exec_progress.get("algo_type"),
        last_error_code=last_error_code,
        last_error_message=last_error_message,
        last_event_at=_to_utc(plan.updated_at),
        owner_service="lifecycle_service",
    )


async def _load_recent_plans(db: AsyncSession, window_minutes: int) -> list[TradingPlan]:
    cutoff = _now() - timedelta(minutes=window_minutes)
    stmt = (
        select(TradingPlan)
        .where(
            (TradingPlan.pipeline_stage.isnot(None))
            | (TradingPlan.updated_at >= cutoff.replace(tzinfo=None))
            | (TradingPlan.created_at >= cutoff.replace(tzinfo=None))
        )
        .order_by(desc(TradingPlan.updated_at), desc(TradingPlan.id))
        .limit(500)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _build_lifecycle_overview(db: AsyncSession, window_minutes: int, only_exceptions: bool) -> LifecycleOverviewResponse:
    distribution = await lifecycle_service.get_pipeline_distribution(db)
    plan_fsm_summary = await lifecycle_service.get_plan_fsm_counts(db)
    position_fsm_summary = await lifecycle_service.get_position_fsm_counts(db)
    recent_plans = await _load_recent_plans(db, window_minutes)

    plan_by_id = {plan.id: plan for plan in recent_plans}
    exceptions_by_id: dict[int, LifecycleExceptionItem] = {}
    all_stage_seconds: list[float] = []
    pipeline: list[LifecycleStageMetric] = []

    for column in distribution.columns:
        warn_count = 0
        critical_count = 0
        stage_seconds: list[float] = []
        oldest_entered_at: datetime | None = None
        last_event_at: datetime | None = None
        for task in column.tasks:
            seconds = _safe_float(task.seconds_in_stage)
            if seconds is not None:
                stage_seconds.append(seconds)
                all_stage_seconds.append(seconds)
            entered_at = _to_utc(task.stage_entered_at)
            if entered_at and (oldest_entered_at is None or entered_at < oldest_entered_at):
                oldest_entered_at = entered_at

            plan = plan_by_id.get(task.plan_id)
            updated_at = _to_utc(plan.updated_at) if plan else None
            if updated_at and (last_event_at is None or updated_at > last_event_at):
                last_event_at = updated_at

            severity = _classify_stage_seconds(column.stage, seconds)
            if severity == "WARN":
                warn_count += 1
            elif severity == "CRITICAL":
                critical_count += 1
                if plan is not None:
                    exceptions_by_id.setdefault(
                        plan.id,
                        _build_exception_from_plan(plan, severity, "阶段停留时间超过阈值"),
                    )

        pipeline.append(
            LifecycleStageMetric(
                stage_id=column.stage,
                stage_key=_stage_key(column.stage, column.stage_name),
                stage_label=column.stage_name,
                active_count=column.count,
                stuck_count=critical_count,
                warn_count=warn_count,
                critical_count=critical_count,
                avg_seconds=_safe_float(column.avg_seconds),
                p50_seconds=_quantile(stage_seconds, 0.5),
                p95_seconds=_quantile(stage_seconds, 0.95),
                oldest_entered_at=oldest_entered_at,
                last_event_at=last_event_at,
            )
        )

    cutoff = _now() - timedelta(minutes=window_minutes)
    for plan in recent_plans:
        if str(plan.plan_status or "").upper() != "FAILED":
            continue
        updated_at = _to_utc(plan.updated_at)
        if updated_at and updated_at < cutoff:
            continue
        exceptions_by_id.setdefault(
            plan.id,
            _build_exception_from_plan(plan, "CRITICAL", "计划进入 FAILED 状态"),
        )

    exceptions = sorted(
        exceptions_by_id.values(),
        key=lambda item: (
            0 if item.severity == "critical" else 1,
            -(item.stayed_seconds or 0),
            item.intent_id,
        ),
    )

    if only_exceptions:
        pipeline = [
            stage for stage in pipeline if stage.warn_count > 0 or stage.critical_count > 0 or stage.stuck_count > 0
        ]

    def _fsm_status(state_key: str, count: int) -> str:
        if state_key == "FAILED" and count > 0:
            return "WARN"
        return "HEALTHY"

    plan_fsm = [
        LifecycleFsmStateMetric(
            state_key=item.state,
            state_label=item.label,
            count=item.count,
            status=_fsm_status(item.state, item.count),
        )
        for item in plan_fsm_summary.states
    ]
    position_fsm = [
        LifecycleFsmStateMetric(
            state_key=item.state,
            state_label=item.label,
            count=item.count,
            status="HEALTHY",
        )
        for item in position_fsm_summary.states
    ]

    return LifecycleOverviewResponse(
        meta=_meta(window_minutes),
        headline=LifecycleHeadlineMetrics(
            active_intents=distribution.total_active,
            stuck_intents=sum(stage.stuck_count for stage in pipeline),
            exception_count=len(exceptions),
            p95_stage_seconds=_quantile(all_stage_seconds, 0.95) or 0.0,
            warn_stage_count=sum(1 for stage in pipeline if stage.warn_count > 0),
            critical_stage_count=sum(1 for stage in pipeline if stage.critical_count > 0),
        ),
        pipeline=pipeline,
        plan_fsm=plan_fsm,
        position_fsm=position_fsm,
        exceptions=exceptions[:50],
    )


async def _build_lifecycle_detail(db: AsyncSession, intent_id: int, window_minutes: int) -> LifecycleIntentDetailResponse:
    result = await db.execute(select(TradingPlan).where(TradingPlan.id == intent_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Intent/plan {intent_id} 不存在")

    stage_history = plan.stage_history if isinstance(plan.stage_history, list) else []
    timeline: list[LifecycleTimelineEvent] = []
    for index, item in enumerate(stage_history, start=1):
        stage_id = int(item.get("stage", -1))
        entered_at = _to_utc(item.get("entered_at"))
        exited_at = _to_utc(item.get("exited_at"))
        duration_seconds = None
        if entered_at:
            duration_seconds = ((exited_at or _now()) - entered_at).total_seconds()
        status = _classify_stage_seconds(stage_id, duration_seconds)
        timeline.append(
            LifecycleTimelineEvent(
                seq=index,
                stage_id=max(stage_id, 0),
                stage_key=_stage_key(stage_id),
                stage_label=PIPELINE_STAGE_NAMES.get(stage_id, f"阶段 {stage_id}"),
                status=status,
                entered_at=entered_at,
                exited_at=exited_at,
                duration_seconds=duration_seconds,
                source_service="pipeline",
                message="阶段流转记录",
                metadata={k: v for k, v in item.items() if k not in {"stage", "entered_at", "exited_at"}},
            )
        )

    fsm_logs = list(
        (
            await db.execute(
                select(FsmTransitionLog)
                .where(FsmTransitionLog.plan_id == plan.id)
                .order_by(FsmTransitionLog.occurred_at.asc(), FsmTransitionLog.id.asc())
                .limit(100)
            )
        ).scalars().all()
    )
    for log in fsm_logs:
        timeline.append(
            LifecycleTimelineEvent(
                seq=len(timeline) + 1,
                stage_id=int(plan.pipeline_stage or 0),
                stage_key=_stage_key(int(plan.pipeline_stage or 0)),
                stage_label=PIPELINE_STAGE_NAMES.get(int(plan.pipeline_stage or 0), "当前阶段"),
                fsm_type=log.fsm_type if log.fsm_type in {"PLAN", "POSITION"} else None,
                fsm_from=log.from_state,
                fsm_to=log.to_state,
                status="CRITICAL" if str(log.to_state).upper() == "FAILED" else "HEALTHY",
                entered_at=_to_utc(log.occurred_at),
                exited_at=None,
                duration_seconds=None,
                source_service="fsm_transition_log",
                message=log.trigger_reason or f"{log.fsm_type} 状态变更",
                metadata={"engine": log.engine, "qty_delta": _safe_float(log.qty_delta)},
            )
        )

    timeline.sort(key=lambda item: (item.entered_at or _now(), item.seq))
    for index, item in enumerate(timeline, start=1):
        item.seq = index

    latest_errors: list[LifecycleExceptionItem] = []
    stage_seconds = None
    entered_at = _to_utc(plan.stage_entered_at)
    if entered_at:
        stage_seconds = (_now() - entered_at).total_seconds()
    stage_severity = _classify_stage_seconds(int(plan.pipeline_stage or 0), stage_seconds)
    if stage_severity in {"WARN", "CRITICAL"}:
        latest_errors.append(_build_exception_from_plan(plan, stage_severity, "当前阶段停留时间超过阈值"))
    if str(plan.plan_status or "").upper() == "FAILED":
        latest_errors.append(_build_exception_from_plan(plan, "CRITICAL", "计划进入 FAILED 状态"))

    try:
        intent_row = (
            await db.execute(
                text(
                    "SELECT idempotency_key FROM autonomous_execution_intent "
                    "WHERE symbol = :symbol ORDER BY updated_at DESC LIMIT 1"
                ),
                {"symbol": plan.symbol},
            )
        ).fetchone()
    except Exception:
        intent_row = None

    return LifecycleIntentDetailResponse(
        meta=_meta(window_minutes),
        intent_id=intent_id,
        idempotency_key=(intent_row[0] if intent_row else None),
        plan_id=plan.id,
        symbol=plan.symbol,
        action=plan.direction,
        signal_type=(plan.plan_tags or {}).get("signal_type") if isinstance(plan.plan_tags, dict) else None,
        execution_path=((plan.plan_tags or {}).get("algo_type") if isinstance(plan.plan_tags, dict) else None),
        autonomy_level=plan.autonomy_action,
        current_stage_id=int(plan.pipeline_stage or 0),
        current_stage_key=_stage_key(int(plan.pipeline_stage or 0)),
        current_stage_label=PIPELINE_STAGE_NAMES.get(int(plan.pipeline_stage or 0), "未知阶段"),
        plan_fsm_state=plan.plan_status,
        position_fsm_state=plan.position_fsm_state,
        started_at=_to_utc(plan.created_at),
        updated_at=_to_utc(plan.updated_at),
        timeline=timeline,
        latest_errors=latest_errors,
    )


def _flow_summary_from_nodes(flow_name: str, flow_label: str, nodes: list[DataFlowNodeStatus]) -> DataFlowSummary:
    lags = [node.lag_seconds for node in nodes if node.lag_seconds is not None]
    critical_nodes = sum(1 for node in nodes if node.status == "CRITICAL")
    warn_nodes = sum(1 for node in nodes if node.status == "WARN")
    status = _status_from_counts(warn_nodes, critical_nodes, unknown=not nodes)
    avg_lag = sum(lags) / len(lags) if lags else None
    max_lag = max(lags) if lags else None
    return DataFlowSummary(
        flow_name=flow_name,
        flow_label=flow_label,
        status=status,
        nodes=nodes,
        total_nodes=len(nodes),
        critical_nodes=critical_nodes,
        warn_nodes=warn_nodes,
        avg_lag_seconds=avg_lag,
        max_lag_seconds=max_lag,
        trend="flat",
    )


def _make_node(
    node_key: str,
    node_label: str,
    *,
    status: str,
    heartbeat_at: datetime | None,
    last_success_at: datetime | None,
    lag_seconds: float | None,
    queue_depth: int | None = None,
    throughput_1m: float | None = None,
    throughput_5m: float | None = None,
    error_count_1h: int = 0,
    error_count_24h: int = 0,
    degraded: bool = False,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    upstream_nodes: Iterable[str] = (),
    downstream_nodes: Iterable[str] = (),
) -> DataFlowNodeStatus:
    return DataFlowNodeStatus(
        node_key=node_key,
        node_label=node_label,
        status=status,
        heartbeat_at=heartbeat_at,
        last_success_at=last_success_at,
        lag_seconds=lag_seconds,
        queue_depth=queue_depth,
        throughput_1m=throughput_1m,
        throughput_5m=throughput_5m,
        error_count_1h=error_count_1h,
        error_count_24h=error_count_24h,
        degraded=degraded,
        last_error_code=last_error_code,
        last_error_message=last_error_message,
        upstream_nodes=list(upstream_nodes),
        downstream_nodes=list(downstream_nodes),
    )


async def _load_latest_timestamp(db: AsyncSession, sqls: Sequence[str]) -> datetime | None:
    for sql in sqls:
        try:
            row = (await db.execute(text(sql))).fetchone()
        except Exception:
            continue
        value = row[0] if row else None
        ts = _to_utc(value)
        if ts is not None:
            return ts
    return None


async def _build_data_flow_payload(db: AsyncSession, window_minutes: int) -> tuple[list[DataFlowSummary], dict[str, list[DataFlowFailureSample]]]:
    lifecycle = await _build_lifecycle_overview(db, window_minutes, False)
    lifecycle_stage_map = {stage.stage_id: stage for stage in lifecycle.pipeline}
    exceptions = lifecycle.exceptions
    snapshot = await situational_awareness_service.get_snapshot(db)
    now = _now()
    has_active_pipeline = lifecycle.headline.active_intents > 0

    signal_ts = await _load_latest_timestamp(db, ["SELECT MAX(created_at) FROM trading_signals"])
    market_ts = await _load_latest_timestamp(db, [
        "SELECT MAX(timestamp) FROM technical_indicators",
        "SELECT MAX(timestamp) FROM technical_indicator",
    ])

    signal_lag = (now - signal_ts).total_seconds() if signal_ts else None
    market_lag = (now - market_ts).total_seconds() if market_ts else None

    signal_status = (
        "HEALTHY"
        if (not has_active_pipeline) or signal_lag is None or signal_lag <= 1800
        else ("WARN" if signal_lag <= 3600 else "CRITICAL")
    )
    market_status = (
        "HEALTHY"
        if (not has_active_pipeline) or market_lag is None or market_lag <= 1800
        else ("WARN" if market_lag <= 3600 else "CRITICAL")
    )

    def _stage_node(stage_id: int, key: str, label: str, upstream: Iterable[str], downstream: Iterable[str]) -> DataFlowNodeStatus:
        metric = lifecycle_stage_map.get(stage_id)
        status = _status_from_counts(
            warn_count=(metric.warn_count if metric else 0),
            critical_count=((metric.critical_count if metric else 0) + (metric.stuck_count if metric else 0)),
            unknown=metric is None,
        )
        return _make_node(
            key,
            label,
            status=status,
            heartbeat_at=metric.last_event_at if metric else None,
            last_success_at=metric.last_event_at if metric else None,
            lag_seconds=metric.p95_seconds if metric else None,
            queue_depth=metric.active_count if metric else None,
            throughput_1m=float(metric.active_count or 0) if metric else None,
            throughput_5m=float(metric.active_count or 0) if metric else None,
            error_count_1h=(metric.critical_count if metric else 0),
            error_count_24h=((metric.warn_count if metric else 0) + (metric.critical_count if metric else 0)),
            degraded=status != "HEALTHY",
            last_error_code="PIPELINE_STUCK" if metric and metric.stuck_count else None,
            last_error_message="阶段存在积压/卡顿" if metric and (metric.warn_count or metric.critical_count or metric.stuck_count) else None,
            upstream_nodes=upstream,
            downstream_nodes=downstream,
        )

    core_nodes = [
        _make_node(
            "signal_generation",
            "Signal Generation",
            status=signal_status,
            heartbeat_at=signal_ts,
            last_success_at=signal_ts,
            lag_seconds=signal_lag if has_active_pipeline else 0.0,
            queue_depth=lifecycle_stage_map.get(1).active_count if lifecycle_stage_map.get(1) else 0,
            throughput_1m=float(lifecycle_stage_map.get(1).active_count or 0) if lifecycle_stage_map.get(1) else None,
            throughput_5m=float(lifecycle_stage_map.get(3).active_count or 0) if lifecycle_stage_map.get(3) else None,
            last_error_code="SIGNAL_STALE" if has_active_pipeline and signal_lag and signal_lag > 1800 else None,
            last_error_message="信号生成长时间无更新" if has_active_pipeline and signal_lag and signal_lag > 1800 else None,
            downstream_nodes=["portfolio_decision"],
        ),
        _stage_node(5, "portfolio_decision", "Portfolio Decision", ["signal_generation"], ["risk_gate"]),
        _stage_node(4, "risk_gate", "Risk Gate", ["portfolio_decision"], ["execution"]),
        _stage_node(8, "execution", "Execution", ["risk_gate"], ["monitoring"]),
        _stage_node(9, "monitoring", "Monitoring", ["execution"], []),
    ]

    market_nodes = [
        _make_node(
            "market_data",
            "Market Data",
            status=market_status,
            heartbeat_at=market_ts,
            last_success_at=market_ts,
            lag_seconds=market_lag if has_active_pipeline else 0.0,
            queue_depth=None,
            throughput_1m=None,
            throughput_5m=None,
            last_error_code="MARKET_DATA_STALE" if has_active_pipeline and market_lag and market_lag > 1800 else None,
            last_error_message="市场数据长时间无更新" if has_active_pipeline and market_lag and market_lag > 1800 else None,
            downstream_nodes=["regime_classification"],
        ),
        _make_node(
            "regime_classification",
            "Regime Classification",
            status="HEALTHY" if snapshot.regime.regime_type else "UNKNOWN",
            heartbeat_at=snapshot.as_of,
            last_success_at=snapshot.as_of,
            lag_seconds=0.0,
            queue_depth=None,
            throughput_1m=None,
            throughput_5m=None,
            degraded=False,
            upstream_nodes=["market_data"],
            downstream_nodes=["situational_awareness"],
        ),
        _make_node(
            "situational_awareness",
            "Situational Awareness",
            status="HEALTHY",
            heartbeat_at=snapshot.as_of,
            last_success_at=snapshot.as_of,
            lag_seconds=0.0,
            queue_depth=snapshot.pending_confirms.count,
            throughput_1m=float(snapshot.active_executions.running_count),
            throughput_5m=float(snapshot.active_executions.count),
            upstream_nodes=["regime_classification"],
            downstream_nodes=[],
        ),
    ]

    post_trade_nodes = [
        _stage_node(12, "settlement", "Settlement", [], ["attribution"]),
        _stage_node(13, "attribution", "Attribution", ["settlement"], ["insight_update"]),
        _stage_node(14, "insight_update", "Insight Update", ["attribution"], ["loop_completed"]),
        _stage_node(16, "loop_completed", "Loop Completed", ["insight_update"], []),
    ]

    flows = [
        _flow_summary_from_nodes("core_trade_pipeline", "主交易流水线", core_nodes),
        _flow_summary_from_nodes("market_data_pipeline", "市场数据更新链路", market_nodes),
        _flow_summary_from_nodes("post_trade_pipeline", "归因与复盘链路", post_trade_nodes),
    ]

    failures: dict[str, list[DataFlowFailureSample]] = {
        "core_trade_pipeline": [
            DataFlowFailureSample(
                sample_id=f"core-{item.intent_id}",
                payload_id=str(item.plan_id or item.intent_id),
                stage_key=item.current_stage_key,
                node_key="execution" if (item.current_stage_id or 0) >= 8 else "signal_generation",
                error_code=item.last_error_code,
                error_message=item.last_error_message,
                occurred_at=item.last_event_at or now,
                recovered_at=None,
                retry_count=0,
                metadata={"symbol": item.symbol, "severity": item.severity},
            )
            for item in exceptions[:20]
        ],
        "market_data_pipeline": [],
        "post_trade_pipeline": [],
    }
    return flows, failures


async def _build_service_payload(db: AsyncSession, window_minutes: int) -> tuple[list[ServiceModuleSummary], list[ServiceHealthItem], dict[str, list[ServiceHealthTimelineEvent]], dict[str, list[DataFlowFailureSample]]]:
    now = _now()
    service_timeline: dict[str, list[ServiceHealthTimelineEvent]] = {}
    service_failures: dict[str, list[DataFlowFailureSample]] = {}
    services: list[ServiceHealthItem] = []

    async def _probe_mysql() -> ServiceHealthItem:
        started = time.perf_counter()
        try:
            await db.execute(text("SELECT 1"))
            latency = (time.perf_counter() - started) * 1000
            return ServiceHealthItem(
                service_key="mysql_primary",
                service_label="MySQL Primary",
                module_key="infrastructure",
                service_kind="infrastructure",
                status="HEALTHY",
                degraded=False,
                latency_ms=latency,
                p95_latency_ms=latency,
                error_count_1h=0,
                error_count_24h=0,
                last_heartbeat_at=now,
                last_success_at=now,
                dependencies=[],
                owners=["platform"],
                tags=["db"],
            )
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000
            return ServiceHealthItem(
                service_key="mysql_primary",
                service_label="MySQL Primary",
                module_key="infrastructure",
                service_kind="infrastructure",
                status="CRITICAL",
                degraded=True,
                latency_ms=latency,
                p95_latency_ms=latency,
                error_count_1h=1,
                error_count_24h=1,
                last_heartbeat_at=now,
                last_success_at=None,
                last_error_code="DB_UNAVAILABLE",
                last_error_message=str(exc)[:240],
                dependencies=[],
                owners=["platform"],
                tags=["db"],
            )

    async def _probe_redis() -> ServiceHealthItem:
        if redis_client is None:
            return ServiceHealthItem(
                service_key="redis_cache",
                service_label="Redis Cache",
                module_key="infrastructure",
                service_kind="infrastructure",
                status="UNKNOWN",
                degraded=False,
                latency_ms=None,
                p95_latency_ms=None,
                error_count_1h=0,
                error_count_24h=0,
                last_heartbeat_at=None,
                last_success_at=None,
                last_error_code=None,
                last_error_message="Redis 未启用",
                dependencies=[],
                owners=["platform"],
                tags=["cache"],
            )
        started = time.perf_counter()
        try:
            await redis_client.ping()
            latency = (time.perf_counter() - started) * 1000
            return ServiceHealthItem(
                service_key="redis_cache",
                service_label="Redis Cache",
                module_key="infrastructure",
                service_kind="infrastructure",
                status="HEALTHY",
                degraded=False,
                latency_ms=latency,
                p95_latency_ms=latency,
                error_count_1h=0,
                error_count_24h=0,
                last_heartbeat_at=now,
                last_success_at=now,
                dependencies=[],
                owners=["platform"],
                tags=["cache"],
            )
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000
            return ServiceHealthItem(
                service_key="redis_cache",
                service_label="Redis Cache",
                module_key="infrastructure",
                service_kind="infrastructure",
                status="WARN",
                degraded=True,
                latency_ms=latency,
                p95_latency_ms=latency,
                error_count_1h=1,
                error_count_24h=1,
                last_heartbeat_at=now,
                last_success_at=None,
                last_error_code="REDIS_UNAVAILABLE",
                last_error_message=str(exc)[:240],
                dependencies=[],
                owners=["platform"],
                tags=["cache"],
            )

    async def _probe_lifecycle() -> ServiceHealthItem:
        overview = await _build_lifecycle_overview(db, window_minutes, False)
        status = _status_from_counts(
            overview.headline.warn_stage_count,
            overview.headline.critical_stage_count,
        )
        return ServiceHealthItem(
            service_key="lifecycle_service",
            service_label="Lifecycle Service",
            module_key="autonomy",
            service_kind="internal",
            status=status,
            degraded=status != "HEALTHY",
            latency_ms=None,
            p95_latency_ms=overview.headline.p95_stage_seconds or None,
            error_count_1h=overview.headline.exception_count,
            error_count_24h=overview.headline.exception_count,
            last_heartbeat_at=overview.meta.generated_at,
            last_success_at=overview.meta.generated_at,
            last_error_code="PIPELINE_EXCEPTIONS" if overview.headline.exception_count else None,
            last_error_message=(
                f"存在 {overview.headline.exception_count} 条生命周期异常" if overview.headline.exception_count else None
            ),
            dependencies=["mysql_primary"],
            owners=["quant-loop"],
            tags=["pipeline", "trading"],
        )

    async def _probe_autonomy_health() -> ServiceHealthItem:
        report = await autonomy_health_monitor.run_all_checks(db)
        status_map = {"OK": "HEALTHY", "WARN": "WARN", "CRITICAL": "CRITICAL"}
        status = status_map.get(report.overall_status, "WARN")
        warn_count = sum(1 for item in report.checks if item.status in {"WARN", "ERROR"})
        critical_count = sum(1 for item in report.checks if item.status == "CRITICAL")
        last_error = next((item for item in report.checks if item.status in {"CRITICAL", "WARN", "ERROR"}), None)
        return ServiceHealthItem(
            service_key="autonomy_health_monitor",
            service_label="Autonomy Health Monitor",
            module_key="autonomy",
            service_kind="internal",
            status=status,
            degraded=status != "HEALTHY",
            latency_ms=None,
            p95_latency_ms=None,
            error_count_1h=critical_count + warn_count,
            error_count_24h=critical_count + warn_count,
            last_heartbeat_at=_to_utc(datetime.fromisoformat(report.generated_at)),
            last_success_at=_to_utc(datetime.fromisoformat(report.generated_at)),
            last_error_code=last_error.name.upper() if last_error else None,
            last_error_message=last_error.message if last_error else None,
            dependencies=["mysql_primary", "redis_cache"],
            owners=["quant-loop"],
            tags=["health", "job-watchdog"],
        )

    async def _probe_situational_awareness() -> ServiceHealthItem:
        snapshot = await situational_awareness_service.get_snapshot(db)
        return ServiceHealthItem(
            service_key="situational_awareness_service",
            service_label="Situational Awareness Service",
            module_key="market_data",
            service_kind="internal",
            status="HEALTHY",
            degraded=False,
            latency_ms=None,
            p95_latency_ms=None,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=snapshot.as_of,
            last_success_at=snapshot.as_of,
            dependencies=["mysql_primary"],
            owners=["observability"],
            tags=["snapshot", "market-data"],
        )

    async def _probe_api_monitoring() -> ServiceHealthItem:
        health = await monitoring_health_check()
        status_map = {"healthy": "HEALTHY", "warning": "WARN", "critical": "CRITICAL"}
        status = status_map.get(str(health.get("status", "healthy")).lower(), "UNKNOWN")
        return ServiceHealthItem(
            service_key="api_monitoring_service",
            service_label="API Monitoring Service",
            module_key="observability",
            service_kind="internal",
            status=status,
            degraded=status != "HEALTHY",
            latency_ms=None,
            p95_latency_ms=None,
            error_count_1h=int(health.get("warning", 0)) + int(health.get("critical", 0)),
            error_count_24h=int(health.get("warning", 0)) + int(health.get("critical", 0)),
            last_heartbeat_at=now,
            last_success_at=now,
            last_error_code="API_RATE_LIMIT" if status in {"WARN", "CRITICAL"} else None,
            last_error_message=(
                f"存在 {health.get('warning', 0)} 个 warning / {health.get('critical', 0)} 个 critical API"
                if status in {"WARN", "CRITICAL"}
                else None
            ),
            dependencies=["redis_cache"],
            owners=["platform"],
            tags=["api", "rate-limit"],
        )

    async def _probe_system_monitor() -> ServiceHealthItem:
        return ServiceHealthItem(
            service_key="system_monitor_aggregator",
            service_label="System Monitor Aggregator",
            module_key="observability",
            service_kind="internal",
            status="HEALTHY",
            degraded=False,
            latency_ms=None,
            p95_latency_ms=None,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=now,
            last_success_at=now,
            dependencies=["mysql_primary", "redis_cache", "lifecycle_service"],
            owners=["observability"],
            tags=["monitoring"],
        )

    for probe in (
        _probe_mysql,
        _probe_redis,
        _probe_lifecycle,
        _probe_autonomy_health,
        _probe_situational_awareness,
        _probe_api_monitoring,
        _probe_system_monitor,
    ):
        service = await probe()
        services.append(service)
        service_timeline[service.service_key] = [
            ServiceHealthTimelineEvent(
                occurred_at=service.last_success_at or service.last_heartbeat_at or now,
                status=service.status,
                message=service.last_error_message or "最近一次探测完成",
                latency_ms=service.latency_ms,
                degraded=service.degraded,
            ),
            ServiceHealthTimelineEvent(
                occurred_at=service.last_heartbeat_at or now,
                status=service.status,
                message="最新心跳",
                latency_ms=service.latency_ms,
                degraded=service.degraded,
            ),
        ]
        service_failures[service.service_key] = []
        if service.last_error_message:
            service_failures[service.service_key].append(
                DataFlowFailureSample(
                    sample_id=f"svc-{service.service_key}",
                    payload_id=service.service_key,
                    stage_key=service.module_key,
                    node_key=service.service_key,
                    error_code=service.last_error_code,
                    error_message=service.last_error_message,
                    occurred_at=service.last_heartbeat_at or now,
                    recovered_at=service.last_recovered_at,
                    retry_count=0,
                    metadata={"tags": service.tags},
                )
            )

    module_counts: dict[str, dict[str, Any]] = {}
    for service in services:
        metrics = module_counts.setdefault(
            service.module_key,
            {
                "total": 0,
                "healthy": 0,
                "warn": 0,
                "critical": 0,
                "unknown": 0,
                "degraded": 0,
                "errors": 0,
                "latencies": [],
            },
        )
        metrics["total"] += 1
        metrics[service.status.lower()] += 1
        metrics["degraded"] += 1 if service.degraded else 0
        metrics["errors"] += service.error_count_24h
        if service.p95_latency_ms is not None:
            metrics["latencies"].append(service.p95_latency_ms)

    modules = [
        ServiceModuleSummary(
            module_key=module_key,
            module_label=_SERVICE_MODULE_LABELS.get(module_key, module_key),
            status=(
                "CRITICAL"
                if stats["critical"]
                else "WARN"
                if stats["warn"] or stats["degraded"]
                else "UNKNOWN"
                if stats["unknown"] == stats["total"]
                else "HEALTHY"
            ),
            total_services=stats["total"],
            healthy_count=stats["healthy"],
            warn_count=stats["warn"],
            critical_count=stats["critical"],
            unknown_count=stats["unknown"],
            degraded_count=stats["degraded"],
            error_count_24h=stats["errors"],
            p95_latency_ms=max(stats["latencies"]) if stats["latencies"] else None,
        )
        for module_key, stats in module_counts.items()
    ]
    return modules, services, service_timeline, service_failures


@router.get("/lifecycle", response_model=LifecycleOverviewResponse, summary="交易生命周期总览")
async def get_lifecycle_overview(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    only_exceptions: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> LifecycleOverviewResponse:
    return await _build_lifecycle_overview(db, window_minutes, only_exceptions)


@router.get("/lifecycle/{intent_id}", response_model=LifecycleIntentDetailResponse, summary="单笔 intent 生命周期详情")
async def get_lifecycle_detail(
    intent_id: int,
    window_minutes: int = Query(default=60, ge=1, le=1440),
    db: AsyncSession = Depends(get_session),
) -> LifecycleIntentDetailResponse:
    return await _build_lifecycle_detail(db, intent_id, window_minutes)


@router.get("/data-flows", response_model=DataFlowOverviewResponse, summary="关键数据流总览")
async def get_data_flows(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    only_degraded: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> DataFlowOverviewResponse:
    flows, _ = await _build_data_flow_payload(db, window_minutes)
    if only_degraded:
        flows = [flow for flow in flows if flow.status != "HEALTHY"]
    return DataFlowOverviewResponse(meta=_meta(window_minutes), flows=flows)


@router.get("/data-flows/{flow_name}", response_model=DataFlowDetailResponse, summary="单条数据流详情")
async def get_data_flow_detail(
    flow_name: str,
    window_minutes: int = Query(default=60, ge=1, le=1440),
    db: AsyncSession = Depends(get_session),
) -> DataFlowDetailResponse:
    flows, failures = await _build_data_flow_payload(db, window_minutes)
    summary = next((item for item in flows if item.flow_name == flow_name), None)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"数据流 {flow_name} 不存在")
    return DataFlowDetailResponse(
        meta=_meta(window_minutes),
        flow_name=summary.flow_name,
        flow_label=summary.flow_label,
        status=summary.status,
        nodes=summary.nodes,
        failures=failures.get(summary.flow_name, []),
    )


@router.get("/services", response_model=ServiceOverviewResponse, summary="模块与服务状态总览")
async def get_service_overview(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    only_degraded: bool = Query(default=False),
    only_external: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> ServiceOverviewResponse:
    modules, services, _, _ = await _build_service_payload(db, window_minutes)
    if only_degraded:
        services = [service for service in services if service.degraded or service.status != "HEALTHY"]
    if only_external:
        services = [service for service in services if service.service_kind == "external"]
    module_keys = {service.module_key for service in services}
    modules = [module for module in modules if module.module_key in module_keys]
    return ServiceOverviewResponse(meta=_meta(window_minutes), modules=modules, services=services)


@router.get("/services/{service_name}", response_model=ServiceDetailResponse, summary="单服务健康详情")
async def get_service_detail(
    service_name: str,
    window_minutes: int = Query(default=60, ge=1, le=1440),
    db: AsyncSession = Depends(get_session),
) -> ServiceDetailResponse:
    modules, services, timelines, failures = await _build_service_payload(db, window_minutes)
    del modules
    service = next((item for item in services if item.service_key == service_name), None)
    if service is None:
        raise HTTPException(status_code=404, detail=f"服务 {service_name} 不存在")
    return ServiceDetailResponse(
        meta=_meta(window_minutes),
        service=service,
        timeline=timelines.get(service.service_key, []),
        recent_failures=failures.get(service.service_key, []),
    )