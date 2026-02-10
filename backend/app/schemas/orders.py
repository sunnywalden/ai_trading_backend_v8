"""V9: Order schemas"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class OrderSubmitRequest(BaseModel):
    symbol: str
    direction: str  # BUY, SELL
    quantity: float
    order_type: str = "MARKET"  # MARKET, LIMIT
    limit_price: Optional[float] = None
    plan_id: Optional[int] = None
    strategy_tag: Optional[str] = None


class OrderView(BaseModel):
    order_id: str
    symbol: str
    direction: str
    quantity: float
    order_type: str
    limit_price: Optional[float] = None
    status: str  # PENDING, FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED
    filled_quantity: float = 0.0
    filled_price: Optional[float] = None
    plan_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrderSubmitResponse(BaseModel):
    status: str = "ok"
    order: OrderView


class OrderStatusResponse(BaseModel):
    status: str = "ok"
    order: OrderView


class OrderHistoryResponse(BaseModel):
    status: str = "ok"
    total: int = 0
    orders: list[OrderView] = []
