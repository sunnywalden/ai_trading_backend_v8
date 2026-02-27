"""V10.2-M6: AI 洞察 + A/B 实验 Pydantic schema"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AIInsightItemResponse(BaseModel):
    id:             int
    insight_type:   str
    regime:         Optional[str]
    symbol:         Optional[str]
    title:          str
    summary:        str
    actionable_rule: Optional[dict]
    confidence:     float
    win_rate_impact: Optional[float]
    validated:      bool
    active:         bool
    applied_count:  int
    success_count:  int
    created_at:     Optional[datetime]

    model_config = {"from_attributes": True}


class InsightListResponse(BaseModel):
    items:  list[AIInsightItemResponse]
    total:  int
    page:   int


class ToggleInsightRequest(BaseModel):
    active: bool


class ABExperimentItemResponse(BaseModel):
    id:               int
    insight_id:       Optional[int]
    experiment_name:  str
    param_key:        str
    status:           str
    start_date:       Optional[datetime]
    end_date:         Optional[datetime]
    control_win_rate: Optional[float]
    treatment_win_rate: Optional[float]
    control_trades:   Optional[int]
    treatment_trades: Optional[int]
    p_value:          Optional[float]
    passed_significance: bool
    auto_applied:     bool

    model_config = {"from_attributes": True}


class ExperimentsListResponse(BaseModel):
    items: list[ABExperimentItemResponse]
    total: int


class CreateExperimentRequest(BaseModel):
    insight_id:       Optional[int] = None
    experiment_name:  str = Field(..., min_length=5)
    param_key:        str
    control_value:    dict
    treatment_value:  dict
    duration_days:    int = Field(default=14, ge=7, le=90)
