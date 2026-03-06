"""V10.4.3: System Monitor DTO Schemas.

统一定义 `/api/v1/system-monitor/*` 的前后端契约，覆盖：
1. 交易生命周期监测
2. 主数据流链路监测
3. 模块与细粒度服务状态
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MonitorStatus = Literal["HEALTHY", "WARN", "CRITICAL", "UNKNOWN"]
SeverityLevel = Literal["info", "warning", "critical"]
FsmType = Literal["PLAN", "POSITION"]
FlowTrend = Literal["up", "flat", "down"]
ServiceKind = Literal["internal", "external", "infrastructure", "job", "stream"]


class MonitorResponseMeta(BaseModel):
    generated_at: datetime
    window_minutes: int = Field(..., ge=1)
    source: str = "system-monitor"
    refresh_interval_seconds: int = Field(default=30, ge=1)


class LifecycleHeadlineMetrics(BaseModel):
    active_intents: int = 0
    stuck_intents: int = 0
    exception_count: int = 0
    p95_stage_seconds: float = 0.0
    warn_stage_count: int = 0
    critical_stage_count: int = 0


class LifecycleStageMetric(BaseModel):
    stage_id: int = Field(..., ge=0)
    stage_key: str
    stage_label: str
    active_count: int = 0
    stuck_count: int = 0
    warn_count: int = 0
    critical_count: int = 0
    avg_seconds: float | None = None
    p50_seconds: float | None = None
    p95_seconds: float | None = None
    oldest_entered_at: datetime | None = None
    last_event_at: datetime | None = None


class LifecycleFsmStateMetric(BaseModel):
    state_key: str
    state_label: str
    count: int = 0
    status: MonitorStatus = "UNKNOWN"


class LifecycleExceptionItem(BaseModel):
    intent_id: int
    plan_id: int | None = None
    symbol: str | None = None
    action: str | None = None
    signal_type: str | None = None
    current_stage_id: int | None = None
    current_stage_key: str | None = None
    current_stage_label: str | None = None
    stayed_seconds: int = 0
    severity: SeverityLevel = "warning"
    execution_path: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_event_at: datetime | None = None
    owner_service: str | None = None


class LifecycleOverviewResponse(BaseModel):
    meta: MonitorResponseMeta
    headline: LifecycleHeadlineMetrics
    pipeline: list[LifecycleStageMetric] = Field(default_factory=list)
    plan_fsm: list[LifecycleFsmStateMetric] = Field(default_factory=list)
    position_fsm: list[LifecycleFsmStateMetric] = Field(default_factory=list)
    exceptions: list[LifecycleExceptionItem] = Field(default_factory=list)


class LifecycleTimelineEvent(BaseModel):
    seq: int = Field(..., ge=1)
    stage_id: int = Field(..., ge=0)
    stage_key: str
    stage_label: str
    fsm_type: FsmType | None = None
    fsm_from: str | None = None
    fsm_to: str | None = None
    status: MonitorStatus = "UNKNOWN"
    entered_at: datetime | None = None
    exited_at: datetime | None = None
    duration_seconds: float | None = None
    source_service: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LifecycleIntentDetailResponse(BaseModel):
    meta: MonitorResponseMeta
    intent_id: int
    idempotency_key: str | None = None
    plan_id: int | None = None
    symbol: str | None = None
    action: str | None = None
    signal_type: str | None = None
    execution_path: str | None = None
    autonomy_level: str | None = None
    current_stage_id: int | None = None
    current_stage_key: str | None = None
    current_stage_label: str | None = None
    plan_fsm_state: str | None = None
    position_fsm_state: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    timeline: list[LifecycleTimelineEvent] = Field(default_factory=list)
    latest_errors: list[LifecycleExceptionItem] = Field(default_factory=list)


class DataFlowNodeStatus(BaseModel):
    node_key: str
    node_label: str
    status: MonitorStatus = "UNKNOWN"
    heartbeat_at: datetime | None = None
    last_success_at: datetime | None = None
    lag_seconds: float | None = None
    queue_depth: int | None = None
    throughput_1m: float | None = None
    throughput_5m: float | None = None
    error_count_1h: int = 0
    error_count_24h: int = 0
    degraded: bool = False
    last_error_code: str | None = None
    last_error_message: str | None = None
    upstream_nodes: list[str] = Field(default_factory=list)
    downstream_nodes: list[str] = Field(default_factory=list)


class DataFlowFailureSample(BaseModel):
    sample_id: str
    payload_id: str | None = None
    stage_key: str | None = None
    node_key: str
    error_code: str | None = None
    error_message: str | None = None
    occurred_at: datetime
    recovered_at: datetime | None = None
    retry_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataFlowSummary(BaseModel):
    flow_name: str
    flow_label: str
    status: MonitorStatus = "UNKNOWN"
    nodes: list[DataFlowNodeStatus] = Field(default_factory=list)
    total_nodes: int = 0
    critical_nodes: int = 0
    warn_nodes: int = 0
    avg_lag_seconds: float | None = None
    max_lag_seconds: float | None = None
    trend: FlowTrend = "flat"


class DataFlowOverviewResponse(BaseModel):
    meta: MonitorResponseMeta
    flows: list[DataFlowSummary] = Field(default_factory=list)


class DataFlowDetailResponse(BaseModel):
    meta: MonitorResponseMeta
    flow_name: str
    flow_label: str
    status: MonitorStatus = "UNKNOWN"
    nodes: list[DataFlowNodeStatus] = Field(default_factory=list)
    failures: list[DataFlowFailureSample] = Field(default_factory=list)


class ServiceModuleSummary(BaseModel):
    module_key: str
    module_label: str
    status: MonitorStatus = "UNKNOWN"
    total_services: int = 0
    healthy_count: int = 0
    warn_count: int = 0
    critical_count: int = 0
    unknown_count: int = 0
    degraded_count: int = 0
    error_count_24h: int = 0
    p95_latency_ms: float | None = None


class ServiceHealthItem(BaseModel):
    service_key: str
    service_label: str
    module_key: str
    service_kind: ServiceKind = "internal"
    status: MonitorStatus = "UNKNOWN"
    degraded: bool = False
    latency_ms: float | None = None
    p95_latency_ms: float | None = None
    error_count_1h: int = 0
    error_count_24h: int = 0
    last_heartbeat_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_recovered_at: datetime | None = None
    dependencies: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ServiceOverviewResponse(BaseModel):
    meta: MonitorResponseMeta
    modules: list[ServiceModuleSummary] = Field(default_factory=list)
    services: list[ServiceHealthItem] = Field(default_factory=list)


class ServiceHealthTimelineEvent(BaseModel):
    occurred_at: datetime
    status: MonitorStatus = "UNKNOWN"
    message: str | None = None
    latency_ms: float | None = None
    degraded: bool = False


class ServiceDetailResponse(BaseModel):
    meta: MonitorResponseMeta
    service: ServiceHealthItem
    timeline: list[ServiceHealthTimelineEvent] = Field(default_factory=list)
    recent_failures: list[DataFlowFailureSample] = Field(default_factory=list)
