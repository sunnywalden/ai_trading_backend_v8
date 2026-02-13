from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic import ConfigDict


class PlanView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: str
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    target_position: float
    plan_status: str
    plan_tags: Optional[Dict[str, Any]] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PlanCreateRequest(BaseModel):
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    target_position: float
    plan_tags: Optional[Dict[str, Any]] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None


class PlanUpdateRequest(BaseModel):
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    target_position: Optional[float] = None
    plan_status: Optional[str] = None
    plan_tags: Optional[Dict[str, Any]] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None


class PlanListResponse(BaseModel):
    status: str = "ok"
    total: int
    plans: list[PlanView]
