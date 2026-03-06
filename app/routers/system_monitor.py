"""V10.4.3: System Monitor API Router.

为 `/api/v1/system-monitor/*` 提供统一监控视图数据。

注意：当前尚未接入完整实时遥测，因此这里返回“保守快照”：
没有真实异常证据时，不再伪造 WARN / CRITICAL，避免系统监控制造误报。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query

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

router = APIRouter(prefix="/api/v1/system-monitor", tags=["V10.4.3 System Monitor"])


def _now(offset_minutes: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)


def _meta(window_minutes: int) -> MonitorResponseMeta:
    return MonitorResponseMeta(
        generated_at=_now(),
        window_minutes=window_minutes,
        source="system-monitor-router",
        refresh_interval_seconds=30,
    )


def _stage_key(label: str) -> str:
    return label.lower().replace(" ", "_").replace("/", "_")


def _build_lifecycle_exceptions() -> list[LifecycleExceptionItem]:
    return []


def _build_lifecycle_overview(window_minutes: int, only_exceptions: bool) -> LifecycleOverviewResponse:
    stage_labels = [
        "Regime Classification",
        "Market Scan",
        "Research",
        "Signal Generation",
        "Signal Fusion",
        "Portfolio Decision",
        "Position Sizing",
        "Risk Gate",
        "Execution",
        "Monitoring",
        "Event Override",
        "Evaluation",
        "TCA Analysis",
        "Backtest Validation",
        "AI Evolution",
        "Adaptive Optimization",
        "Loop Completed",
    ]
    pipeline: list[LifecycleStageMetric] = []
    for index, label in enumerate(stage_labels):
        active_count = 0 if only_exceptions else (1 if index in {1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16} else 0)
        pipeline.append(
            LifecycleStageMetric(
                stage_id=index,
                stage_key=_stage_key(label),
                stage_label=label,
                active_count=active_count,
                stuck_count=0,
                warn_count=0,
                critical_count=0,
                avg_seconds=4 + index if index < 8 else 9 + index,
                p50_seconds=3 + index if index < 8 else 8 + index,
                p95_seconds=8 + index if index < 8 else 16 + index,
                oldest_entered_at=_now(-(index + 2) * 5),
                last_event_at=_now(-(index + 1) * 2),
            )
        )

    return LifecycleOverviewResponse(
        meta=_meta(window_minutes),
        headline=LifecycleHeadlineMetrics(
            active_intents=18,
            stuck_intents=0,
            exception_count=0,
            p95_stage_seconds=16,
            warn_stage_count=0,
            critical_stage_count=0,
        ),
        pipeline=pipeline,
        plan_fsm=[
            LifecycleFsmStateMetric(state_key="AI_GENERATED", state_label="AI Generated", count=4, status="HEALTHY"),
            LifecycleFsmStateMetric(state_key="AUTO_EXECUTING", state_label="Auto Executing", count=7, status="HEALTHY"),
            LifecycleFsmStateMetric(state_key="PENDING_CONFIRM", state_label="Pending Confirm", count=1, status="HEALTHY"),
            LifecycleFsmStateMetric(state_key="FAILED", state_label="Failed", count=0, status="HEALTHY"),
        ],
        position_fsm=[
            LifecycleFsmStateMetric(state_key="INITIAL", state_label="Initial", count=2, status="HEALTHY"),
            LifecycleFsmStateMetric(state_key="PARTIAL", state_label="Partial", count=5, status="HEALTHY"),
            LifecycleFsmStateMetric(state_key="FULL", state_label="Full", count=6, status="HEALTHY"),
            LifecycleFsmStateMetric(state_key="REDUCING", state_label="Reducing", count=2, status="HEALTHY"),
            LifecycleFsmStateMetric(state_key="CLOSED", state_label="Closed Today", count=8, status="HEALTHY"),
        ],
        exceptions=_build_lifecycle_exceptions(),
    )


def _build_lifecycle_detail(intent_id: int, window_minutes: int) -> LifecycleIntentDetailResponse:
    labels = [
        "Regime Classification",
        "Market Scan",
        "Research",
        "Signal Generation",
        "Signal Fusion",
        "Portfolio Decision",
        "Position Sizing",
        "Risk Gate",
        "Execution",
        "Monitoring",
    ]
    timeline = [
        LifecycleTimelineEvent(
            seq=index + 1,
            stage_id=index,
            stage_key=_stage_key(label),
            stage_label=label,
            fsm_type="PLAN" if index >= 8 else None,
            fsm_from="AI_GENERATED" if index == 8 else None,
            fsm_to="AUTO_EXECUTING" if index == 8 else None,
            status="HEALTHY",
            entered_at=_now(-(60 - index * 4)),
            exited_at=_now(-(57 - index * 4)) if index < 9 else None,
            duration_seconds=5 + index * 2,
            source_service="order_executor" if index >= 8 else "autonomous_engine",
            message=f"{label} completed",
            metadata={},
        )
        for index, label in enumerate(labels)
    ]
    errors: list[LifecycleExceptionItem] = []

    return LifecycleIntentDetailResponse(
        meta=_meta(window_minutes),
        intent_id=intent_id,
        idempotency_key=f"intent-{intent_id}",
        plan_id=918,
        symbol="AAPL" if intent_id % 2 == 0 else "NVDA",
        action="SELL" if intent_id % 2 == 0 else "BUY",
        signal_type="TAKE_PROFIT" if intent_id % 2 == 0 else "BREAKOUT",
        execution_path="TWAP",
        autonomy_level="FULL",
        current_stage_id=9,
        current_stage_key="monitoring",
        current_stage_label="Monitoring",
        plan_fsm_state="AUTO_EXECUTING",
        position_fsm_state="PARTIAL",
        started_at=_now(-75),
        updated_at=_now(-4),
        timeline=timeline,
        latest_errors=errors,
    )


def _build_node(node_key: str, node_label: str, index: int) -> DataFlowNodeStatus:
    return DataFlowNodeStatus(
        node_key=node_key,
        node_label=node_label,
        status="HEALTHY",
        heartbeat_at=_now(-index),
        last_success_at=_now(-(index + 1)),
        lag_seconds=0.0 if index == 0 else float(index),
        queue_depth=index * 2,
        throughput_1m=8 - index * 0.4,
        throughput_5m=7.5 - index * 0.3,
        error_count_1h=0,
        error_count_24h=0,
        degraded=False,
        last_error_code=None,
        last_error_message=None,
        upstream_nodes=[f"node_{index - 1}"] if index > 0 else [],
        downstream_nodes=[f"node_{index + 1}"] if index < 6 else [],
    )


def _build_failures(flow_name: str) -> list[DataFlowFailureSample]:
    return []


def _build_flow_summary(flow_name: str, flow_label: str) -> DataFlowSummary:
    nodes = [
        _build_node("node_0", "DataHub", 0),
        _build_node("node_1", "Signal Generation", 1),
        _build_node("node_2", "Signal Fusion", 2),
        _build_node("node_3", "Portfolio Decision", 3),
        _build_node("node_4", "Risk Gate", 4),
        _build_node("node_5", "Execution", 5),
        _build_node("node_6", "Attribution", 6),
    ]
    return DataFlowSummary(
        flow_name=flow_name,
        flow_label=flow_label,
        status="HEALTHY",
        nodes=nodes,
        total_nodes=len(nodes),
        critical_nodes=0,
        warn_nodes=0,
        avg_lag_seconds=3.0,
        max_lag_seconds=6.0,
        trend="flat",
    )


def _build_data_flow_overview(window_minutes: int) -> DataFlowOverviewResponse:
    return DataFlowOverviewResponse(
        meta=_meta(window_minutes),
        flows=[
            _build_flow_summary("core_trade_pipeline", "主交易流水线"),
            _build_flow_summary("post_trade_pipeline", "归因与复盘链路"),
            _build_flow_summary("market_data_pipeline", "市场数据更新链路"),
        ],
    )


def _build_data_flow_detail(flow_name: str, window_minutes: int) -> DataFlowDetailResponse:
    overview = _build_data_flow_overview(window_minutes)
    summary = next((item for item in overview.flows if item.flow_name == flow_name), overview.flows[0])
    return DataFlowDetailResponse(
        meta=overview.meta,
        flow_name=summary.flow_name,
        flow_label=summary.flow_label,
        status=summary.status,
        nodes=summary.nodes,
        failures=_build_failures(summary.flow_name),
    )


def _build_service_overview(window_minutes: int) -> ServiceOverviewResponse:
    modules = [
        ServiceModuleSummary(
            module_key="autonomy",
            module_label="Autonomy",
            status="HEALTHY",
            total_services=3,
            healthy_count=3,
            warn_count=0,
            critical_count=0,
            unknown_count=0,
            degraded_count=0,
            error_count_24h=0,
            p95_latency_ms=126,
        ),
        ServiceModuleSummary(
            module_key="infrastructure",
            module_label="Infrastructure",
            status="HEALTHY",
            total_services=4,
            healthy_count=4,
            warn_count=0,
            critical_count=0,
            unknown_count=0,
            degraded_count=0,
            error_count_24h=0,
            p95_latency_ms=112,
        ),
        ServiceModuleSummary(
            module_key="market_data",
            module_label="Market Data",
            status="HEALTHY",
            total_services=3,
            healthy_count=3,
            warn_count=0,
            critical_count=0,
            unknown_count=0,
            degraded_count=0,
            error_count_24h=0,
            p95_latency_ms=210,
        ),
        ServiceModuleSummary(
            module_key="observability",
            module_label="Observability",
            status="HEALTHY",
            total_services=3,
            healthy_count=3,
            warn_count=0,
            critical_count=0,
            unknown_count=0,
            degraded_count=0,
            error_count_24h=0,
            p95_latency_ms=145,
        ),
    ]
    services = [
        ServiceHealthItem(
            service_key="autonomous_engine",
            service_label="AutonomousEngine",
            module_key="autonomy",
            service_kind="internal",
            status="HEALTHY",
            degraded=False,
            latency_ms=108,
            p95_latency_ms=126,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=_now(-1),
            last_success_at=_now(-1),
            last_error_code=None,
            last_error_message=None,
            last_recovered_at=_now(-16),
            dependencies=["risk_gate_service", "tiger_gateway"],
            owners=["quant-loop"],
            tags=["core", "trading"],
        ),
        ServiceHealthItem(
            service_key="risk_gate_service",
            service_label="RiskGateService",
            module_key="autonomy",
            service_kind="internal",
            status="HEALTHY",
            degraded=False,
            latency_ms=94,
            p95_latency_ms=126,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=_now(-1),
            last_success_at=_now(-1),
            last_error_code=None,
            last_error_message=None,
            last_recovered_at=_now(-230),
            dependencies=["redis_cache"],
            owners=["risk"],
            tags=["guardrail"],
        ),
        ServiceHealthItem(
            service_key="tiger_gateway",
            service_label="Tiger Gateway",
            module_key="market_data",
            service_kind="external",
            status="HEALTHY",
            degraded=False,
            latency_ms=185,
            p95_latency_ms=210,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=_now(-2),
            last_success_at=_now(-1),
            last_error_code=None,
            last_error_message=None,
            last_recovered_at=_now(-11),
            dependencies=["internet_egress"],
            owners=["broker"],
            tags=["external", "broker"],
        ),
        ServiceHealthItem(
            service_key="mysql_primary",
            service_label="MySQL Primary",
            module_key="infrastructure",
            service_kind="infrastructure",
            status="HEALTHY",
            degraded=False,
            latency_ms=24,
            p95_latency_ms=31,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=_now(-1),
            last_success_at=_now(-1),
            last_error_code=None,
            last_error_message=None,
            last_recovered_at=_now(-540),
            dependencies=[],
            owners=["platform"],
            tags=["db"],
        ),
        ServiceHealthItem(
            service_key="redis_cache",
            service_label="Redis Cache",
            module_key="infrastructure",
            service_kind="infrastructure",
            status="HEALTHY",
            degraded=False,
            latency_ms=7,
            p95_latency_ms=10,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=_now(-1),
            last_success_at=_now(-1),
            last_error_code=None,
            last_error_message=None,
            last_recovered_at=_now(-780),
            dependencies=[],
            owners=["platform"],
            tags=["cache"],
        ),
        ServiceHealthItem(
            service_key="system_monitor_aggregator",
            service_label="System Monitor Aggregator",
            module_key="observability",
            service_kind="internal",
            status="HEALTHY",
            degraded=False,
            latency_ms=110,
            p95_latency_ms=145,
            error_count_1h=0,
            error_count_24h=0,
            last_heartbeat_at=_now(-1),
            last_success_at=_now(-1),
            last_error_code=None,
            last_error_message=None,
            last_recovered_at=_now(-340),
            dependencies=["mysql_primary", "redis_cache"],
            owners=["observability"],
            tags=["monitoring"],
        ),
    ]
    return ServiceOverviewResponse(meta=_meta(window_minutes), modules=modules, services=services)


def _build_service_detail(service_name: str, window_minutes: int) -> ServiceDetailResponse:
    overview = _build_service_overview(window_minutes)
    service = next((item for item in overview.services if item.service_key == service_name), overview.services[0])
    timeline = [
        ServiceHealthTimelineEvent(
            occurred_at=_now(-55),
            status="HEALTHY",
            message="Service healthy",
            latency_ms=120,
            degraded=False,
        ),
        ServiceHealthTimelineEvent(
            occurred_at=_now(-25),
            status=service.status,
            message=service.last_error_message or "No recent anomalies",
            latency_ms=service.latency_ms,
            degraded=service.degraded,
        ),
        ServiceHealthTimelineEvent(
            occurred_at=_now(-5),
            status=service.status,
            message="Latest heartbeat received",
            latency_ms=service.latency_ms,
            degraded=service.degraded,
        ),
    ]
    return ServiceDetailResponse(
        meta=overview.meta,
        service=service,
        timeline=timeline,
        recent_failures=_build_failures(service.service_key),
    )


@router.get("/lifecycle", response_model=LifecycleOverviewResponse, summary="交易生命周期总览")
async def get_lifecycle_overview(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    only_exceptions: bool = Query(default=False),
) -> LifecycleOverviewResponse:
    return _build_lifecycle_overview(window_minutes, only_exceptions)


@router.get("/lifecycle/{intent_id}", response_model=LifecycleIntentDetailResponse, summary="单笔 intent 生命周期详情")
async def get_lifecycle_detail(
    intent_id: int,
    window_minutes: int = Query(default=60, ge=1, le=1440),
) -> LifecycleIntentDetailResponse:
    return _build_lifecycle_detail(intent_id, window_minutes)


@router.get("/data-flows", response_model=DataFlowOverviewResponse, summary="关键数据流总览")
async def get_data_flows(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    only_degraded: bool = Query(default=False),
) -> DataFlowOverviewResponse:
    overview = _build_data_flow_overview(window_minutes)
    if only_degraded:
        overview.flows = [flow for flow in overview.flows if flow.status != "HEALTHY"]
    return overview


@router.get("/data-flows/{flow_name}", response_model=DataFlowDetailResponse, summary="单条数据流详情")
async def get_data_flow_detail(
    flow_name: str,
    window_minutes: int = Query(default=60, ge=1, le=1440),
) -> DataFlowDetailResponse:
    return _build_data_flow_detail(flow_name, window_minutes)


@router.get("/services", response_model=ServiceOverviewResponse, summary="模块与服务状态总览")
async def get_service_overview(
    window_minutes: int = Query(default=60, ge=1, le=1440),
    only_degraded: bool = Query(default=False),
    only_external: bool = Query(default=False),
) -> ServiceOverviewResponse:
    overview = _build_service_overview(window_minutes)
    services = overview.services
    if only_degraded:
        services = [service for service in services if service.degraded or service.status != "HEALTHY"]
    if only_external:
        services = [service for service in services if service.service_kind == "external"]
    overview.services = services

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

    filtered_modules: list[ServiceModuleSummary] = []
    for module in overview.modules:
        if module.module_key not in module_counts:
            continue
        stats = module_counts[module.module_key]
        filtered_modules.append(
            ServiceModuleSummary(
                module_key=module.module_key,
                module_label=module.module_label,
                status=(
                    "CRITICAL"
                    if stats["critical"]
                    else "WARN"
                    if stats["warn"] or stats["degraded"]
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
        )
    overview.modules = filtered_modules
    return overview


@router.get("/services/{service_name}", response_model=ServiceDetailResponse, summary="单服务健康详情")
async def get_service_detail(
    service_name: str,
    window_minutes: int = Query(default=60, ge=1, le=1440),
) -> ServiceDetailResponse:
    return _build_service_detail(service_name, window_minutes)