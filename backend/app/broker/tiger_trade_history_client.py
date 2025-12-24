from datetime import datetime, timedelta
from typing import List
import asyncio
from concurrent.futures import ThreadPoolExecutor

from tigeropen.tiger_open_config import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.common.consts import SecurityType, Market

from app.core.config import settings
from .trade_history_client_base import TradeHistoryClient
from .history_models import TradeRecord, DailyPnlRecord, TradeSide


class TigerTradeHistoryClient(TradeHistoryClient):
    """老虎证券历史成交 / PnL 客户端（基于官方 tigeropen SDK）

    使用 TradeClient 获取历史成交数据和盈亏记录。
    """

    def __init__(self, private_key_path: str, tiger_id: str, account: str):
        """初始化 Tiger 客户端

        Args:
            private_key_path: RSA 私钥文件路径
            tiger_id: 开发者 ID
            account: 交易账户号
        """
        self.account = account
        self.client_config = get_client_config(
            private_key_path=private_key_path,
            tiger_id=tiger_id,
            account=account
        )
        self.trade_client = TradeClient(self.client_config)
        self._executor = ThreadPoolExecutor(max_workers=2)

    async def _run_in_executor(self, func, *args, **kwargs):
        """在线程池中运行同步的 SDK 调用"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

    async def list_trades(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> List[TradeRecord]:
        """获取历史成交记录

        使用 TradeClient.get_filled_orders() 获取已成交订单
        """
        results: List[TradeRecord] = []

        try:
            # 将 datetime 转为毫秒时间戳
            start_time = int(start.timestamp() * 1000)
            end_time = int(end.timestamp() * 1000)

            # 获取美股成交记录
            filled_orders = await self._run_in_executor(
                self.trade_client.get_filled_orders,
                account=account_id,
                sec_type=SecurityType.STK,
                market=Market.US,
                start_time=start_time,
                end_time=end_time
            )

            if filled_orders:
                for order in filled_orders:
                    if not order.contract:
                        continue

                    # 确定买卖方向
                    side_str = getattr(order, 'action', 'BUY').upper()
                    side: TradeSide = "BUY" if side_str == "BUY" else "SELL"

                    # 解析时间戳
                    order_time = getattr(order, 'order_time', None)
                    if order_time:
                        ts = datetime.fromtimestamp(order_time / 1000.0)
                    else:
                        ts = datetime.utcnow()

                    # 获取已成交数量和平均成交价
                    filled_qty = getattr(order, 'filled', 0)
                    avg_fill_price = getattr(order, 'avg_fill_price', 0)

                    # 获取已实现盈亏（如果有）
                    realized_pnl = getattr(order, 'realized_pnl', None)

                    if filled_qty > 0 and avg_fill_price > 0:
                        tr = TradeRecord(
                            symbol=order.contract.symbol,
                            side=side,
                            quantity=float(filled_qty),
                            price=float(avg_fill_price),
                            timestamp=ts,
                            realized_pnl=float(realized_pnl) if realized_pnl is not None else None,
                            order_id=str(getattr(order, 'id', '')),
                        )
                        results.append(tr)

            # 如果需要添加期权成交记录，可以再查询一次
            # option_orders = await self._run_in_executor(
            #     self.trade_client.get_filled_orders,
            #     account=account_id,
            #     sec_type=SecurityType.OPT,
            #     market=Market.US,
            #     start_time=start_time,
            #     end_time=end_time
            # )
            # ... 类似处理 ...

        except Exception as e:
            print(f"[TigerTradeHistoryClient] Error fetching trade history: {e}")

        # 按时间排序
        results.sort(key=lambda t: t.timestamp)
        return results

    async def list_daily_pnl(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> List[DailyPnlRecord]:
        """获取日度盈亏记录

        注：老虎 SDK 可能不直接提供日度 PnL 接口，
        可以从成交记录中聚合计算，或者使用资产接口。
        这里返回空列表作为示例。
        """
        # TODO: 实现日度 PnL 查询逻辑
        return []
