"""V9: Price Alert schemas"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AlertCreateRequest(BaseModel):
    symbol: str
    condition_type: str  # price_above, price_below, pct_change, rsi_cross, macd_cross
    threshold: float
    action: str = "notify"  # notify, auto_execute
    linked_plan_id: Optional[int] = None


class AlertUpdateRequest(BaseModel):
    threshold: Optional[float] = None
    action: Optional[str] = None
    alert_status: Optional[str] = None


class AlertView(BaseModel):
    id: int
    account_id: str
    symbol: str
    condition_type: str
    threshold: float
    action: str
    linked_plan_id: Optional[int] = None
    alert_status: str
    triggered_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AlertListResponse(BaseModel):
    status: str = "ok"
    total: int = 0
    alerts: list[AlertView] = []


class AlertHistoryView(BaseModel):
    id: int
    alert_id: int
    symbol: str
    trigger_price: float
    trigger_time: datetime
    notification_sent: bool
    action_taken: Optional[str] = None


class AlertHistoryResponse(BaseModel):
    status: str = "ok"
    total: int = 0
    history: list[AlertHistoryView] = []
