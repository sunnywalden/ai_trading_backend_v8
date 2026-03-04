from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class MarketUniverseMarketStatus(BaseModel):
    market: str
    active_symbols: int
    last_synced_at: Optional[datetime] = None
    stale: bool


class MarketUniverseStatusResponse(BaseModel):
    status: str = "ok"
    degraded: bool
    degraded_reasons: List[str]
    markets: List[MarketUniverseMarketStatus]
    recent_fallback_runs_24h: int
    checked_at: datetime
