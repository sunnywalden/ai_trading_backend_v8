from datetime import datetime
from typing import List

from .trade_history_client_base import TradeHistoryClient
from .history_models import TradeRecord, DailyPnlRecord


class DummyTradeHistoryClient(TradeHistoryClient):
    """占位实现：返回空的成交和 PnL 数据。

    用于本地开发或未配置真实券商 API 的情况。
    """

    async def list_trades(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> List[TradeRecord]:
        return []

    async def list_daily_pnl(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> List[DailyPnlRecord]:
        return []
