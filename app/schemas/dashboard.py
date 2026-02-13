"""V9: Dashboard schemas"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DashboardExposure(BaseModel):
    delta_pct: float = 0.0
    gamma_pct: float = 0.0
    vega_pct: float = 0.0
    theta_pct: float = 0.0


class DashboardSignal(BaseModel):
    symbol: str
    signal_type: str
    message: str
    timestamp: datetime
    severity: str = "info"


class DashboardAction(BaseModel):
    action_type: str
    message: str
    link: Optional[str] = None


class DashboardSummaryResponse(BaseModel):
    status: str = "ok"
    account_id: str
    total_equity: float = 0.0
    cash: float = 0.0
    market_value: float = 0.0
    daily_pnl: float = 0.0
    daily_return_pct: float = 0.0
    mtd_return_pct: float = 0.0
    ytd_return_pct: float = 0.0
    plan_execution_rate: float = 0.0
    active_plans_count: int = 0
    risk_level: str = "UNKNOWN"
    exposure: DashboardExposure = DashboardExposure()
    recent_signals: list[DashboardSignal] = []
    pending_actions: list[DashboardAction] = []
