"""V9: Equity & PnL schemas"""
from pydantic import BaseModel
from typing import Optional
from datetime import date


class EquitySnapshotView(BaseModel):
    snapshot_date: date
    total_equity: float
    cash: float = 0.0
    market_value: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    daily_return: Optional[float] = None
    cumulative_return: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    benchmark_return: Optional[float] = None


class EquitySnapshotsResponse(BaseModel):
    status: str = "ok"
    account_id: str
    snapshots: list[EquitySnapshotView] = []


class PnlAttributionItem(BaseModel):
    label: str
    pnl: float
    pct: float = 0.0
    trade_count: int = 0


class PnlAttributionResponse(BaseModel):
    status: str = "ok"
    account_id: Optional[str] = None
    group_by: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_pnl: float = 0.0
    items: list[PnlAttributionItem] = []
