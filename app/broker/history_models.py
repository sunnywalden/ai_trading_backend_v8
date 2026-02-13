from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal


TradeSide = Literal["BUY", "SELL"]


@dataclass
class TradeRecord:
    """单笔成交记录（从老虎历史成交或对账单中抽象出来）"""
    symbol: str
    side: TradeSide
    quantity: float
    price: float
    timestamp: datetime
    realized_pnl: Optional[float] = None  # 若 Tiger 提供每笔盈亏则填入
    order_id: Optional[str] = None


@dataclass
class DailyPnlRecord:
    """可选：用于日度行为和风险分析的 PnL 汇总"""
    symbol: str
    date: datetime
    realized_pnl: float
    unrealized_pnl: float
    net_pnl: float
