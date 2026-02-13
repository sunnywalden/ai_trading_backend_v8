from datetime import datetime
from typing import List, Protocol

from .history_models import TradeRecord, DailyPnlRecord


class TradeHistoryClient(Protocol):
    """历史成交 & 日度 PnL 统一接口。

    后续如果你接的不仅是老虎，而是多家券商，只要都实现这个协议即可。
    """

    async def list_trades(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> List[TradeRecord]:
        """在给定时间区间内返回成交明细（按时间排序）。

        - 建议仅返回已成交记录（非委托）
        - 返回时最好已经按 timestamp 升序
        """
        ...

    async def list_daily_pnl(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> List[DailyPnlRecord]:
        """可选：返回日度 PnL 汇总，用于更精细的行为分析。

        若券商接口不方便提供，可返回空列表。
        """
        ...
