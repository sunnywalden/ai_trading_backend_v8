"""V10.5.2: Capacity Arbiter API DTO Schemas

前后端契约定义，覆盖：
  POST /api/v1/capacity/preview    → 预演仲裁（dry-run）
  GET  /api/v1/capacity/logs       → 仲裁历史日志列表
  GET  /api/v1/capacity/logs/{id}  → 单条日志详情
  GET  /api/v1/capacity/stats      → 仲裁指标摘要
  GET  /api/v1/capacity/config     → 查看容量配置
  PATCH /api/v1/capacity/config    → 热更新容量配置
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# 候选池条目
# ─────────────────────────────────────────────────────────────────────────────


class CandidateSnapshot(BaseModel):
    symbol: str
    type: str  # POSITION | SIGNAL
    candidate_type: Optional[str] = None  # POSITION | SIGNAL（前端友好别名）
    raw_score: float
    admission_score: float
    protected: bool = False
    is_protected: Optional[bool] = None
    protect_reason: Optional[str] = None
    hold_minutes: Optional[float] = None
    recommendation: Optional[str] = None
    signal_id: Optional[int] = None
    rank: int = 0
    eliminate: bool = False
    eliminated_reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 预演请求 / 响应
# ─────────────────────────────────────────────────────────────────────────────


class CapacityPreviewRequest(BaseModel):
    account_id: str
    regime: str = "SIDEWAYS"
    dry_run: bool = True


class EliminatedPosition(BaseModel):
    symbol: str
    overall_score: Optional[float] = None
    hold_minutes: Optional[float] = None
    recommendation: Optional[str] = None


class EliminatedSignal(BaseModel):
    signal_id: Optional[int] = None
    symbol: str
    conviction_score: Optional[float] = None


class ApprovedSignal(BaseModel):
    signal_id: Optional[int] = None
    symbol: str
    admission_score: Optional[float] = None


class CapacityPreviewResponse(BaseModel):
    cycle_id: str
    overflow: int
    max_positions: int
    positions_count: int
    signals_count: int
    approved_signals: List[ApprovedSignal]
    rejected_signals: List[EliminatedSignal]
    positions_to_close: List[str]
    candidates_snapshot: List[CandidateSnapshot]
    min_edge_protected: int = 0
    cooldown_protected: int = 0
    min_hold_protected: int = 0
    max_replacements_cap: int = 0
    replacement_triggered: bool = False
    dry_run: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# 日志列表
# ─────────────────────────────────────────────────────────────────────────────


class CapacityLogItem(BaseModel):
    id: int
    account_id: str
    cycle_id: Optional[str]
    regime: Optional[str]
    trigger_reason: str
    max_positions: int
    positions_count: int
    signals_count: int
    overflow_count: int
    min_edge_protected: int
    cooldown_protected: int
    min_hold_protected: int
    max_replacements_cap: int
    dry_run: bool
    replacement_triggered: bool
    created_at: datetime

    # 简要摘要（从 JSON 字段派生）
    eliminated_positions_count: int = 0
    eliminated_signals_count: int = 0
    approved_signals_count: int = 0


class CapacityLogListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[CapacityLogItem]


class CapacityLogDetailResponse(CapacityLogItem):
    candidates_snapshot: List[CandidateSnapshot] = []
    eliminated_positions: List[Any] = []
    eliminated_signals: List[Any] = []
    approved_signals_detail: List[Any] = []


# ─────────────────────────────────────────────────────────────────────────────
# 仲裁统计摘要
# ─────────────────────────────────────────────────────────────────────────────


class CapacityStatsResponse(BaseModel):
    window_days: int = 7
    total_arbitrations: int = 0
    total_replacements: int = 0
    replacement_rate: float = 0.0  # replacements / arbitrations
    total_signals_rejected: int = 0
    total_positions_closed: int = 0
    min_edge_protection_rate: float = 0.0
    cooldown_protection_rate: float = 0.0
    avg_overflow: float = 0.0
    dry_run_pct: float = 0.0
    # 席位使用趋势（过去 N 天的每日快照）
    seat_utilization_trend: List[dict] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# 配置查看 / 更新
# ─────────────────────────────────────────────────────────────────────────────


class CapacityConfigResponse(BaseModel):
    capacity_replacement_enabled: bool
    capacity_replacement_dry_run: bool
    capacity_replacement_max_per_cycle: int
    capacity_replacement_min_edge: float
    capacity_min_hold_minutes: int
    capacity_replacement_cooldown_minutes: int
    max_concurrent_positions: int  # 来自 SignalQualityConfig


class CapacityConfigPatchRequest(BaseModel):
    capacity_replacement_enabled: Optional[bool] = None
    capacity_replacement_dry_run: Optional[bool] = None
    capacity_replacement_max_per_cycle: Optional[int] = None
    capacity_replacement_min_edge: Optional[float] = None
    capacity_min_hold_minutes: Optional[int] = None
    capacity_replacement_cooldown_minutes: Optional[int] = None
