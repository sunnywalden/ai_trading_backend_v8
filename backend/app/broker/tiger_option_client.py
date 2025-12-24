from typing import List
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

from tigeropen.tiger_open_config import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import SecurityType, Market

from .option_client_base import OptionBrokerClient
from .models import OptionPosition, UnderlyingPosition, OptionContract, Greeks


class TigerOptionClient(OptionBrokerClient):
    """老虎证券期权敞口客户端（基于官方 tigeropen SDK）

    使用老虎证券官方 Python SDK (tigeropen) 实现：
    - TradeClient：获取持仓信息
    - QuoteClient：获取期权 Greeks 和实时行情
    """

    def __init__(self, private_key_path: str, tiger_id: str, account: str):
        """初始化 Tiger 客户端

        Args:
            private_key_path: RSA 私钥文件路径 (.pem 格式)
            tiger_id: 开发者 ID（从老虎开放平台获取）
            account: 交易账户号
        """
        self.account = account
        # 使用官方 SDK 配置
        self.client_config = get_client_config(
            private_key_path=private_key_path,
            tiger_id=tiger_id,
            account=account
        )
        self.trade_client = TradeClient(self.client_config)
        self.quote_client = QuoteClient(self.client_config)
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def _run_in_executor(self, func, *args):
        """在线程池中运行同步的 SDK 调用"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    async def list_underlying_positions(self, account_id: str) -> List[UnderlyingPosition]:
        """获取股票/ETF 仓位

        使用 TradeClient.get_positions() 获取股票持仓
        """
        results: List[UnderlyingPosition] = []

        try:
            # 获取美股持仓
            positions = await self._run_in_executor(
                self.trade_client.get_positions,
                sec_type=SecurityType.STK,
                market=Market.US
            )

            for pos in positions:
                if not pos.contract or not pos.contract.symbol:
                    continue

                underlying = UnderlyingPosition(
                    symbol=pos.contract.symbol,
                    market="US",
                    quantity=int(pos.quantity or 0),
                    avg_price=float(pos.average_cost or 0),
                    last_price=float(pos.market_price or 0),
                    currency=pos.contract.currency or "USD",
                )
                results.append(underlying)

            # 如果需要支持港股，可以再查询一次
            # hk_positions = await self._run_in_executor(
            #     self.trade_client.get_positions,
            #     sec_type=SecurityType.STK,
            #     market=Market.HK
            # )
            # ... 类似处理 ...

        except Exception as e:
            print(f"[TigerOptionClient] Error fetching underlying positions: {e}")

        return results

    async def list_option_positions(self, account_id: str) -> List[OptionPosition]:
        """获取期权仓位 + Greeks

        使用 TradeClient.get_positions() 获取期权持仓，
        然后用 QuoteClient.get_option_briefs() 获取 Greeks
        """
        results: List[OptionPosition] = []

        try:
            # 获取期权持仓
            positions = await self._run_in_executor(
                self.trade_client.get_positions,
                sec_type=SecurityType.OPT,
                market=Market.US
            )

            if not positions:
                return results

            # 构建期权合约标识列表，用于批量查询 Greeks
            symbols = [pos.contract.symbol for pos in positions if pos.contract]

            # 批量获取期权行情和 Greeks
            option_briefs = {}
            if symbols:
                try:
                    briefs = await self._run_in_executor(
                        self.quote_client.get_option_briefs,
                        symbols
                    )
                    if briefs:
                        for brief in briefs:
                            if hasattr(brief, 'identifier'):
                                option_briefs[brief.identifier] = brief
                            elif hasattr(brief, 'symbol'):
                                option_briefs[brief.symbol] = brief
                except Exception as e:
                    print(f"[TigerOptionClient] Error fetching option Greeks: {e}")

            ts = datetime.utcnow().timestamp()

            for pos in positions:
                if not pos.contract:
                    continue

                contract_obj = pos.contract
                symbol = contract_obj.symbol

                # 解析期权合约信息
                contract = OptionContract(
                    broker_symbol=symbol,
                    underlying=getattr(contract_obj, 'underlying', symbol.split()[0] if ' ' in symbol else symbol),
                    market="US",
                    right=getattr(contract_obj, 'right', 'CALL'),
                    strike=float(getattr(contract_obj, 'strike', 0)),
                    expiry=getattr(contract_obj, 'expiry', datetime.now().date()),
                    multiplier=int(getattr(contract_obj, 'multiplier', 100)),
                    currency=getattr(contract_obj, 'currency', 'USD'),
                )

                # 获取 Greeks（从行情数据或持仓数据）
                brief = option_briefs.get(symbol)
                if brief:
                    greeks = Greeks(
                        delta=float(getattr(brief, 'delta', 0)),
                        gamma=float(getattr(brief, 'gamma', 0)),
                        vega=float(getattr(brief, 'vega', 0)),
                        theta=float(getattr(brief, 'theta', 0)),
                    )
                    underlying_price = float(getattr(brief, 'underlying_price', 0))
                else:
                    # 如果没有行情数据，使用默认值
                    greeks = Greeks(delta=0, gamma=0, vega=0, theta=0)
                    underlying_price = float(getattr(pos, 'market_price', 0))

                option_pos = OptionPosition(
                    contract=contract,
                    quantity=int(pos.quantity or 0),
                    avg_price=float(pos.average_cost or 0),
                    underlying_price=underlying_price,
                    greeks=greeks,
                    last_update_ts=ts,
                )
                results.append(option_pos)

        except Exception as e:
            print(f"[TigerOptionClient] Error fetching option positions: {e}")

        return results
