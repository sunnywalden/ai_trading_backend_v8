"""V10.2-M3: 仓位生命周期 Pydantic schema"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LifecycleStatusResponse(BaseModel):
    position_id:     int
    symbol:          str
    current_state:   str
    decision:        str
    quantity_delta:  float
    reason:          str
    trailing_high:   Optional[float] = None
    fused_confidence: Optional[float] = None


class ScaleInCandidateItem(BaseModel):
    position_id:   int
    symbol:        str
    decision:      str
    quantity_delta: float
    reason:        str
    confidence:    float


class ScaleInCandidatesResponse(BaseModel):
    candidates: list[ScaleInCandidateItem]
    count:      int


class ManualScaleRequest(BaseModel):
    direction:   str  = Field(..., pattern="^(IN|OUT)$", description="IN=加仓 OUT=减仓")
    quantity:    float = Field(..., gt=0)
    reason:      str  = Field(..., min_length=5)


class ManualScaleResponse(BaseModel):
    success:    bool
    message:    str
    applied_qty: float
