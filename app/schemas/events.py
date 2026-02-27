"""V10.2-M2: 事件日历 Pydantic 响应 / 请求 schema"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EventCalendarItemResponse(BaseModel):
    id:              int
    symbol:          str
    event_type:      str
    event_date:      datetime
    title:           str
    description:     Optional[str] = None
    eps_estimate:    Optional[float] = None
    eps_actual:      Optional[float] = None
    risk_level:      str
    requires_fence:  bool
    fence_applied:   bool
    fence_overridden: bool
    source:          str

    model_config = {"from_attributes": True}


class EventCalendarListResponse(BaseModel):
    items:  list[EventCalendarItemResponse]
    total:  int
    days:   int


class EarningsFenceStatusResponse(BaseModel):
    symbol:       str
    active:       bool
    reason:       str
    event_id:     Optional[int] = None
    event_date:   Optional[datetime] = None
    max_size_pct: float
    overridden:   bool
    override_reason: Optional[str] = None


class ActiveFencesResponse(BaseModel):
    fences: list[EarningsFenceStatusResponse]


class OverrideFenceRequest(BaseModel):
    event_id: int = Field(..., description="被覆盖的事件 ID")
    reason:   str = Field(..., min_length=5, description="人工覆盖原因（至少 5 字符）")


class RecordEarningsResultRequest(BaseModel):
    symbol:          str
    eps_actual:      float
    revenue_actual:  Optional[float] = None
    notes:           Optional[str]   = None


class EarningsResultResponse(BaseModel):
    success: bool
    message: str
