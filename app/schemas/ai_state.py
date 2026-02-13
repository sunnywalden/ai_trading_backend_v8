from typing import Dict
from pydantic import BaseModel


class LimitsView(BaseModel):
    max_order_notional_usd: float
    max_total_gamma_pct: float
    max_total_vega_pct: float
    max_total_theta_pct: float


class ExposureView(BaseModel):
    equity_usd: float
    total_delta_notional_usd: float
    total_gamma_usd: float
    total_vega_usd: float
    total_theta_usd: float
    short_dte_gamma_usd: float
    short_dte_vega_usd: float
    short_dte_theta_usd: float
    delta_pct: float
    gamma_pct: float
    vega_pct: float
    theta_pct: float
    short_dte_gamma_pct: float
    short_dte_theta_pct: float



class SymbolBehaviorView(BaseModel):
    symbol: str
    tier: str
    behavior_score: int
    sell_fly_score: int
    overtrade_score: int
    revenge_score: int
    discipline_score: int

    # 原始行为指标，便于前端直观展示
    trade_count: int
    sell_fly_events: int
    sell_fly_extra_cost_ratio: float
    overtrade_index: float
    revenge_events: int


class AiStateView(BaseModel):
    trade_mode: str
    limits: LimitsView
    exposure: ExposureView
    symbols: Dict[str, SymbolBehaviorView]
