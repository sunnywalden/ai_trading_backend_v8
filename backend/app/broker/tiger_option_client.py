from typing import List
from datetime import datetime, date
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

    async def _run_in_executor(self, func, *args, **kwargs):
        """在线程池中运行同步的 SDK 调用"""
        loop = asyncio.get_event_loop()
        if kwargs:
            return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))
        return await loop.run_in_executor(self._executor, func, *args)

    async def list_underlying_positions(self, account_id: str) -> List[UnderlyingPosition]:
        """获取股票/ETF 仓位

        使用 TradeClient.get_positions() 获取股票持仓
        """
        results: List[UnderlyingPosition] = []

        try:
            print(f"[TigerOptionClient] Fetching underlying positions for account: {account_id}")
            
            # 获取美股持仓
            us_positions = await self._run_in_executor(
                self.trade_client.get_positions,
                sec_type=SecurityType.STK,
                market=Market.US
            )
            
            print(f"[TigerOptionClient] Got {len(us_positions) if us_positions else 0} US underlying positions")

            if us_positions:
                for pos in us_positions:
                    if not pos.contract or not pos.contract.symbol:
                        print(f"[TigerOptionClient] Skipping position without contract/symbol")
                        continue
                    
                    symbol = pos.contract.symbol
                    quantity = int(pos.quantity or 0)
                    
                    # 跳过数量为0的持仓
                    if quantity == 0:
                        print(f"[TigerOptionClient] Skipping {symbol} with zero quantity")
                        continue

                    print(f"[TigerOptionClient] US Position: {symbol}, qty={quantity}")
                    
                    underlying = UnderlyingPosition(
                        symbol=symbol,
                        market="US",
                        quantity=quantity,
                        avg_price=float(pos.average_cost or 0),
                        last_price=float(pos.market_price or 0),
                        currency=pos.contract.currency or "USD",
                    )
                    results.append(underlying)

            # 获取港股持仓
            try:
                hk_positions = await self._run_in_executor(
                    self.trade_client.get_positions,
                    sec_type=SecurityType.STK,
                    market=Market.HK
                )
                
                print(f"[TigerOptionClient] Got {len(hk_positions) if hk_positions else 0} HK underlying positions")
                
                if hk_positions:
                    for pos in hk_positions:
                        if not pos.contract or not pos.contract.symbol:
                            print(f"[TigerOptionClient] Skipping HK position without contract/symbol")
                            continue
                        
                        symbol = pos.contract.symbol
                        quantity = int(pos.quantity or 0)
                        
                        # 跳过数量为0的持仓
                        if quantity == 0:
                            print(f"[TigerOptionClient] Skipping HK {symbol} with zero quantity")
                            continue
                        
                        print(f"[TigerOptionClient] HK Position: {symbol}, qty={quantity}")
                        
                        underlying = UnderlyingPosition(
                            symbol=symbol,
                            market="HK",
                            quantity=quantity,
                            avg_price=float(pos.average_cost or 0),
                            last_price=float(pos.market_price or 0),
                            currency=pos.contract.currency or "HKD",
                        )
                        results.append(underlying)
            except Exception as hk_error:
                print(f"[TigerOptionClient] Error fetching HK positions: {hk_error}")
            
            print(f"[TigerOptionClient] Total positions to return: {len(results)}")

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
            print(f"[TigerOptionClient] Fetching option positions for account: {account_id}")
            # 获取期权持仓
            positions = await self._run_in_executor(
                self.trade_client.get_positions,
                sec_type=SecurityType.OPT,
                market=Market.US
            )
            
            print(f"[TigerOptionClient] Got {len(positions) if positions else 0} option positions")

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

                # 解析 expiry - Tiger API 可能返回字符串或 date 对象
                raw_expiry = getattr(contract_obj, 'expiry', None)
                if isinstance(raw_expiry, str):
                    try:
                        expiry_date = datetime.strptime(raw_expiry, '%Y-%m-%d').date()
                    except ValueError:
                        # 如果格式不匹配，使用当前日期作为默认值
                        expiry_date = datetime.now().date()
                elif isinstance(raw_expiry, date):
                    expiry_date = raw_expiry
                else:
                    expiry_date = datetime.now().date()

                # 解析期权合约信息
                contract = OptionContract(
                    broker_symbol=symbol,
                    underlying=getattr(contract_obj, 'underlying', symbol.split()[0] if ' ' in symbol else symbol),
                    market="US",
                    right=getattr(contract_obj, 'right', 'CALL'),
                    strike=float(getattr(contract_obj, 'strike', 0)),
                    expiry=expiry_date,
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

    async def get_account_id(self) -> str:
        """获取真实的券商账户ID（从 API 返回的实际账户号）"""
        try:
            # 尝试获取账户资产，从中提取真实账户ID
            assets = await self._run_in_executor(
                self.trade_client.get_assets,
                account=self.account
            )
            if assets and hasattr(assets, 'account'):
                return str(assets.account)
        except Exception as e:
            print(f"[TigerOptionClient] Error fetching account ID: {e}")
        
        # 降级返回配置的账户名
        return self.account

    async def get_account_equity(self, account_id: str) -> float:
        """获取账户权益（净清算价值）
        
        返回账户的总资产价值（USD）
        """
        try:
            print(f"[TigerOptionClient] Fetching account equity for: {account_id}")
            assets = await self._run_in_executor(
                self.trade_client.get_assets,
                account=account_id
            )
            
            if assets:
                print(f"[TigerOptionClient] Got assets object: {type(assets)}")
                
                # 如果是列表，取第一个元素
                if isinstance(assets, list) and len(assets) > 0:
                    asset = assets[0]
                    print(f"[TigerOptionClient] Using first asset from list")
                else:
                    asset = assets
                
                # 优先使用 summary.net_liquidation（净清算价值）
                if hasattr(asset, 'summary') and asset.summary:
                    # summary 是一个对象，不是字典
                    if hasattr(asset.summary, 'net_liquidation'):
                        net_liq = asset.summary.net_liquidation
                        # Tiger API 可能返回 inf，需要检查
                        if net_liq and net_liq != float('inf'):
                            print(f"[TigerOptionClient] Net liquidation: {net_liq}")
                            return float(net_liq)
                
                # 降级尝试其他字段
                for attr in ['net_liquidation', 'equity_with_loan', 'total_cash_balance']:
                    value = getattr(asset, attr, None)
                    if value and value != float('inf'):
                        print(f"[TigerOptionClient] Using {attr}: {value}")
                        return float(value)
                
                print(f"[TigerOptionClient] Warning: Could not find valid equity value in assets")
            else:
                print(f"[TigerOptionClient] Warning: assets is None")
                        
        except Exception as e:
            print(f"[TigerOptionClient] Error fetching account equity: {e}")
            import traceback
            traceback.print_exc()
        
        # 如果获取失败，返回 None（由调用方决定默认值）
        print(f"[TigerOptionClient] Returning None for equity")
        return None
