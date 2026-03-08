"""V10.3: 智能订单簿 Pydantic Schemas"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Risk Badges ───────────────────────────────────────────────────────────────
class RiskBadgeInfo(BaseModel):
    type: str           # VAR_HIGH / FENCE_ACTIVE / ALGO_RUNNING / LOW_LIQUIDITY / EXPIRING / MARGIN_CALL
    label: str
    icon: str
    severity: str       # warning / danger / info


# ── Single Order Row ──────────────────────────────────────────────────────────
class OrderBookRow(BaseModel):
    plan_id: int
    account_id: str
    symbol: str
    execution_intent_db_id: Optional[int] = None
    execution_intent_key: Optional[str] = None
    broker_order_id: Optional[str] = None
    market: Optional[str] = None           # US / HK / CN
    direction: Optional[str] = None        # BUY / SELL
    strategy_source: Optional[str] = None  # 策略名称

    # Pipeline
    pipeline_stage: Optional[int] = None
    pipeline_stage_name: Optional[str] = None

    # 价格
    entry_price_target: Optional[float] = None
    entry_price_low: Optional[float] = None
    entry_price_high: Optional[float] = None
    fill_avg_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # 仓位 & 损益
    target_position_pct: Optional[float] = None
    current_position_pct: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None

    # AI 置信度
    confidence: Optional[float] = None
    six_dim_scores: Optional[dict] = None   # 迷你雷达图数据

    # 风险标志
    risk_badges: list[RiskBadgeInfo] = Field(default_factory=list)

    # AI 摘要（最多80字）
    ai_summary: Optional[str] = None

    # 状态
    plan_status: str = "ACTIVE"
    autonomy_action: Optional[str] = None
    source: Optional[str] = None
    position_fsm_state: Optional[str] = None

    # 时间
    created_at: datetime
    updated_at: datetime
    valid_until: Optional[datetime] = None

    # 分组标识
    group: str = "active"   # active / monitoring / completed


# ── Filter Params ─────────────────────────────────────────────────────────────
class OrderBookFilter(BaseModel):
    direction: Optional[str] = None          # BUY / SELL
    account_id: Optional[str] = None
    market: Optional[str] = None
    plan_type: Optional[str] = None
    stage_min: Optional[int] = None
    stage_max: Optional[int] = None
    strategy_source: Optional[str] = None
    has_risk_badge: Optional[str] = None     # VAR_HIGH / FENCE_ACTIVE / ...
    confidence_min: Optional[float] = None
    confidence_max: Optional[float] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None             # symbol 模糊搜索


# ── Order Book Response ───────────────────────────────────────────────────────
class OrderBookGroup(BaseModel):
    group_id: str       # active / monitoring / completed
    group_label: str
    count: int
    items: list[OrderBookRow]


class OrderBookResponse(BaseModel):
    groups: list[OrderBookGroup]
    total: int
    as_of: datetime


# ── Summary ───────────────────────────────────────────────────────────────────
class OrderBookSummary(BaseModel):
    total_active: int = 0
    total_monitoring: int = 0
    total_completed_today: int = 0
    total_unrealized_pnl: float = 0.0
    avg_confidence: Optional[float] = None
    buy_count: int = 0
    sell_count: int = 0
    as_of: datetime


# ── Stop Loss Update ──────────────────────────────────────────────────────────
class StopLossUpdateRequest(BaseModel):
    new_stop_loss: float = Field(..., description="新止损价格", gt=0)
    reason: Optional[str] = Field(None, description="调整原因", max_length=200)


class StopLossUpdateResponse(BaseModel):
    plan_id: int
    old_stop_loss: float
    new_stop_loss: float
    updated_at: datetime
