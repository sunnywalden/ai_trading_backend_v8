from typing import List, Literal, Optional
from pydantic import BaseModel


OrderSide = Literal["BUY", "SELL"]
OrderInstrument = Literal["STOCK", "OPTION"]


class PositionSnapshot(BaseModel):
    symbol: str
    instrument: OrderInstrument
    quantity: float
    avg_price: float
    market_value: float


class RiskPreference(BaseModel):
    level: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    max_drawdown_pct: float = 0.2
    target_vol_pct: float = 0.25


class AdviceOrderSuggestion(BaseModel):
    symbol: str
    instrument: OrderInstrument
    side: OrderSide
    quantity: float
    note: str
    intent: Literal["ENTRY", "TAKE_PROFIT", "STOP_LOSS", "HEDGE", "REBALANCE"]


class AiAdviceRequest(BaseModel):
    account_id: Optional[str] = None
    goal: str
    time_horizon: Literal["INTRADAY", "SWING", "POSITION"] = "SWING"
    risk_preference: RiskPreference = RiskPreference()
    notes: Optional[str] = None


class AiAdviceResponse(BaseModel):
    summary: str
    reasoning: str
    suggested_orders: List[AdviceOrderSuggestion]


class StockSymbol(BaseModel):
    symbol: str
    name: Optional[str] = None
    market: Literal["US", "HK"]


class SymbolSearchResponse(BaseModel):
    items: List[StockSymbol]


class KlineAnalysisRequest(BaseModel):
    symbol: str


class KlineAnalysisResponse(BaseModel):
    symbol: str
    prediction: str  # 走势预测
    suggestion: str  # 操作建议
    direction: Literal["LONG", "SHORT", "NEUTRAL"]
    action: Literal["BUY", "SELL", "HOLD", "EMPTY", "INCREASE"]
    details: str     # 详细分析
