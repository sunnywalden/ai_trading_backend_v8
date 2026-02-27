"""V10.3: 全局态势感知 Pydantic Schemas"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── 6 数据块 ──────────────────────────────────────────────────────────────────
class RegimeBlock(BaseModel):
    regime_type: Optional[str] = None       # BULL_TREND / BEAR_TREND / HIGH_VOL / etc.
    regime_label: Optional[str] = None
    confidence: Optional[float] = None      # 0-100
    trend_direction: Optional[str] = None   # up / down / flat
    color: str = "#6b7280"                  # Tailwind-like hex


class VarBlock(BaseModel):
    current_pct: float = 0.0         # 当前组合VaR%
    limit_pct: float = 2.0           # 限制%（通常2%）
    usage_ratio: float = 0.0         # current/limit 0-1
    level: str = "green"             # green / yellow / red (>60% / >80% / >100%)


class ActiveFenceEntry(BaseModel):
    symbol: str
    fence_type: str      # EARNINGS / FOMC / CPI / NFP
    expires_at: Optional[datetime] = None


class ActiveFencesBlock(BaseModel):
    count: int = 0
    entries: list[ActiveFenceEntry] = Field(default_factory=list)


class ActiveExecutionEntry(BaseModel):
    plan_id: int
    symbol: str
    algo_type: str       # TWAP / VWAP
    fill_pct: float      # 0-100


class ActiveExecutionsBlock(BaseModel):
    count: int = 0
    entries: list[ActiveExecutionEntry] = Field(default_factory=list)


class PendingConfirmsBlock(BaseModel):
    count: int = 0
    symbols: list[str] = Field(default_factory=list)   # 最多3个
    is_flashing: bool = False                          # count > 0 时为 True


class AutonomyBlock(BaseModel):
    level: str = "ADVISORY"          # FULL / SEMI / ADVISORY
    level_label: str = "建议模式"
    is_running: bool = False
    color: str = "#8b5cf6"


# ── Situational Awareness Snapshot ───────────────────────────────────────────
class SituationalAwarenessSnapshot(BaseModel):
    regime: RegimeBlock
    var: VarBlock
    active_fences: ActiveFencesBlock
    active_executions: ActiveExecutionsBlock
    pending_confirms: PendingConfirmsBlock
    autonomy: AutonomyBlock
    as_of: datetime


# ── WebSocket Push Payload ────────────────────────────────────────────────────
class SaWebSocketMessage(BaseModel):
    type: str = "sa_update"
    data: SituationalAwarenessSnapshot
