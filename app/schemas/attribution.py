"""V10.2-M5: 交易归因 Pydantic schema"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class TradeAttributionItemResponse(BaseModel):
    id:                int
    symbol:            str
    pnl_pct:           float
    pnl_absolute:      float
    hold_days:         int
    category:          str
    alpha_source:      Optional[str]
    alpha_contribution_pct: Optional[float]
    alpha_detail:      Optional[dict]
    execution_score:   Optional[float]
    slippage_pct:      Optional[float]
    timing_score:      Optional[float]
    position_mgmt_score: Optional[float]
    scale_in_count:    int
    scale_out_reason:  Optional[str]
    regime_at_entry:   Optional[str]
    created_at:        Optional[datetime]

    model_config = {"from_attributes": True}


class TradeAttributionListResponse(BaseModel):
    items:  list[TradeAttributionItemResponse]
    total:  int


class AttributionSummaryItem(BaseModel):
    category:        str
    count:           int
    avg_pnl_pct:     float
    avg_exec_score:  float
    avg_pos_score:   float


class AttributionSummaryResponse(BaseModel):
    period_days: int
    breakdown:   list[AttributionSummaryItem]
