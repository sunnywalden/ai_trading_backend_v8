"""V10.3: 交易生命周期中心 Pydantic Schemas"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ── Pipeline 阶段定义 ─────────────────────────────────────────────────────────
PIPELINE_STAGE_NAMES: dict[int, str] = {
    0: "体制分类",
    1: "信号融合",
    2: "策略匹配",
    3: "计划生成",
    4: "风险门控",
    5: "自主决策",
    6: "人工审核",
    7: "下单执行",
    8: "算法执行",
    9: "持仓监控",
    10: "仓位调整",
    11: "离场触发",
    12: "订单结算",
    13: "归因分析",
    14: "洞察更新",
    15: "A/B实验",
    16: "已完成",
}

# P50 基准（秒）；None 表示持续性阶段
PIPELINE_P50_BENCHMARKS: dict[int, Optional[int]] = {
    0: 60,
    1: 30,
    2: 10,
    3: 120,
    4: 5,
    5: 5,
    6: 300,
    7: 10,
    8: 3600,
    9: None,
    10: 60,
    11: 30,
    12: 60,
    13: 120,
    14: 300,
    15: 60,
    16: None,
}


# ── Pipeline 类型 ─────────────────────────────────────────────────────────────
class PipelineTaskCard(BaseModel):
    plan_id: int
    symbol: str
    direction: Optional[str] = None  # BUY / SELL
    confidence: Optional[float] = None
    source: Optional[str] = None
    stage_entered_at: Optional[datetime] = None
    seconds_in_stage: Optional[int] = None  # 已在当前阶段停留秒数
    delay_level: str = "green"  # green / yellow / red / stopped


class PipelineStageColumn(BaseModel):
    stage: int
    stage_name: str
    p50_benchmark: Optional[int] = None
    count: int = 0
    avg_seconds: Optional[float] = None
    tasks: list[PipelineTaskCard] = Field(default_factory=list)


class PipelineDistribution(BaseModel):
    columns: list[PipelineStageColumn]
    total_active: int
    as_of: datetime


# ── Plan FSM ─────────────────────────────────────────────────────
PLAN_FSM_STATES = [
    "AI_GENERATED",
    "AUTO_EXECUTING",
    "PENDING_CONFIRM",
    "EXECUTED",
    "REVOKED",
    "FAILED",
    "CANCELLED",
    "EXPIRED",
    "ACTIVE",
]


class PlanFsmStateCount(BaseModel):
    state: str
    label: str
    count: int
    color: str  # CSS 颜色


class PlanFsmSummary(BaseModel):
    states: list[PlanFsmStateCount]
    total: int
    as_of: datetime


# ── Position FSM ─────────────────────────────────────────────────
POSITION_FSM_STATES = [
    "PENDING",
    "OPENING",
    "ACTIVE",
    "SCALING_IN",
    "SCALING_OUT",
    "PARTIALLY_CLOSED",
    "CLOSING",
    "EXCEPTION",
    "LIQUIDATED",
    "CLOSED",
]


class PositionFsmStateCount(BaseModel):
    state: str
    label: str
    count: int
    color: str


class EngineStats(BaseModel):
    scale_in_count: int = 0
    scale_out_count: int = 0
    trailing_stop_count: int = 0
    total_triggers: int = 0


class PositionFsmSummary(BaseModel):
    states: list[PositionFsmStateCount]
    engine_stats: EngineStats
    total: int
    as_of: datetime
    source: Optional[str] = None
    mismatch_detected: bool = False
    mismatch_symbols: list[str] = Field(default_factory=list)


class LifecycleCoherenceSummary(BaseModel):
    account_id: Optional[str] = None
    source: str = "UNKNOWN"
    active_positions: int = 0
    broker_active_positions: int = 0
    lifecycle_active_positions: int = 0
    mismatch_detected: bool = False
    mismatch_symbols: list[str] = Field(default_factory=list)
    stale_plans_closed: int = 0
    stale_positions_closed: int = 0
    hydrated_positions_created: int = 0
    reconciled_plan_ids: list[int] = Field(default_factory=list)
    reconciled_position_ids: list[int] = Field(default_factory=list)
    hydrated_position_ids: list[int] = Field(default_factory=list)
    run_mode: str = "inspect_only"
    notes: list[str] = Field(default_factory=list)
    as_of: datetime


# ── FSM Transition Events ────────────────────────────────────────
class FsmTransitionEvent(BaseModel):
    id: int
    plan_id: int
    symbol: Optional[str] = None
    fsm_type: str  # PLAN / POSITION
    from_state: Optional[str] = None
    to_state: str
    engine: Optional[str] = None
    qty_delta: Optional[float] = None
    trigger_reason: Optional[str] = None
    occurred_at: datetime


class FsmEventPage(BaseModel):
    items: list[FsmTransitionEvent]
    total: int
    page: int
    size: int


# ── Decision Provenance ──────────────────────────────────────────
class SixDimScore(BaseModel):
    dimension: str  # technical/fundamental/macro/volatility/options/sentiment
    label: str
    raw_score: float
    regime_multiplier: float
    weighted_contribution: float
    contribution_pct: float


class RiskGateCheck(BaseModel):
    check_name: str
    label: str
    passed: bool
    detail: Optional[str] = None


class ExecProgress(BaseModel):
    algo_type: Optional[str] = None  # TWAP / VWAP
    total_slices: int = 0
    filled_slices: int = 0
    fill_pct: float = 0.0
    avg_fill_price: Optional[float] = None


# ── Position Board (持仓看板 – groups Position by status) ───────
class PositionBoardCard(BaseModel):
    id: int
    symbol: str
    direction: Optional[str] = None
    total_qty: float = 0.0
    avg_entry_price: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    hold_seconds: Optional[int] = None  # seconds in current state
    latest_plan_id: Optional[int] = None


class PositionBoardColumn(BaseModel):
    state: str
    label: str
    color: str
    count: int = 0
    cards: list[PositionBoardCard] = Field(default_factory=list)


class PositionBoard(BaseModel):
    columns: list[PositionBoardColumn]
    total_active: int
    as_of: datetime
    source: Optional[str] = None
    mismatch_detected: bool = False
    mismatch_symbols: list[str] = Field(default_factory=list)


# ── Decision Provenance ──────────────────────────────────────────
class DecisionProvenance(BaseModel):
    plan_id: int
    symbol: str
    direction: Optional[str] = None
    created_at: datetime
    # 5 卡片
    six_dim_scores: list[SixDimScore] = Field(default_factory=list)
    risk_gate_checks: list[RiskGateCheck] = Field(default_factory=list)
    ai_reasoning: Optional[str] = None
    exec_progress: Optional[ExecProgress] = None
    position_fsm_state: Optional[str] = None
    # 元数据
    regime: Optional[str] = None
    confidence: Optional[float] = None
    autonomy_action: Optional[str] = None
