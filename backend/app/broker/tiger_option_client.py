from typing import List, Dict
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, date
import asyncio
from concurrent.futures import ThreadPoolExecutor

from tigeropen.tiger_open_config import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.quote.quote_client import QuoteClient
from tigeropen.common.consts import SecurityType, Market, OrderStatus
from tigeropen.trade.domain.order import Order

from .option_client_base import OptionBrokerClient
from .models import OptionPosition, UnderlyingPosition, OptionContract, Greeks
from app.core.cache import cache


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
    
    async def _get_hk_stock_names_from_cache(self, symbols: List[str]) -> Dict[str, str]:
        """从缓存获取港股名称
        
        Args:
            symbols: 股票代码列表
            
        Returns:
            {symbol: name} 字典，只返回缓存中有的
        """
        result = {}
        for symbol in symbols:
            cache_key = f"hk_stock_name:{symbol}"
            name = await cache.get(cache_key)
            if name:
                result[symbol] = name
                print(f"[TigerOptionClient] Got HK stock name from cache: {symbol} -> {name}")
        return result
    
    async def _set_hk_stock_names_to_cache(self, stock_names: Dict[str, str]):
        """将港股名称存入缓存
        
        Args:
            stock_names: {symbol: name} 字典
        """
        for symbol, name in stock_names.items():
            if name:
                cache_key = f"hk_stock_name:{symbol}"
                # 缓存 30 天（股票名称几乎不变）
                await cache.set(cache_key, name, expire=30*24*3600)
                print(f"[TigerOptionClient] Cached HK stock name: {symbol} -> {name}")
    
    async def _fetch_hk_stock_names(self, symbols: List[str]) -> Dict[str, str]:
        """从 Tiger API 批量获取港股名称
        
        Args:
            symbols: 股票代码列表
            
        Returns:
            {symbol: name} 字典
        """
        stock_names = {}
        if not symbols:
            return stock_names
            
        try:
            briefs = await self._run_in_executor(
                self.quote_client.get_stock_briefs,
                symbols
            )
            if briefs is not None and len(briefs) > 0:
                for i, row in briefs.iterrows():
                    sym = row.get('symbol')
                    # 尝试多个字段获取名称（优先使用中文名称）
                    name = row.get('nameCN') or row.get('name_cn') or row.get('localSymbol') or row.get('name')
                    if sym and name:
                        stock_names[sym] = name
                        print(f"[TigerOptionClient] Fetched HK stock name from API: {sym} -> {name}")
        except Exception as e:
            print(f"[TigerOptionClient] Error fetching HK stock names from API: {e}")
        
        return stock_names
    
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
                market=Market.US,
                account=account_id
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
                    market=Market.HK,
                    account=account_id
                )
                
                print(f"[TigerOptionClient] Got {len(hk_positions) if hk_positions else 0} HK underlying positions")
                
                if hk_positions:
                    # 收集所有港股symbol，批量获取股票信息
                    hk_symbols = []
                    hk_position_map = {}
                    for pos in hk_positions:
                        if not pos.contract or not pos.contract.symbol:
                            continue
                        symbol = pos.contract.symbol
                        quantity = int(pos.quantity or 0)
                        if quantity == 0:
                            continue
                        hk_symbols.append(symbol)
                        hk_position_map[symbol] = pos
                    
                    # 首先从缓存获取股票名称
                    stock_names = await self._get_hk_stock_names_from_cache(hk_symbols)
                    
                    # 找出缓存中没有的symbol
                    missing_symbols = [sym for sym in hk_symbols if sym not in stock_names]
                    
                    # 如果有缺失的，从 API 获取
                    if missing_symbols:
                        print(f"[TigerOptionClient] Fetching {len(missing_symbols)} HK stock names from API")
                        new_names = await self._fetch_hk_stock_names(missing_symbols)
                        
                        # 合并结果
                        stock_names.update(new_names)
                        
                        # 将新获取的名称存入缓存
                        if new_names:
                            await self._set_hk_stock_names_to_cache(new_names)
                    else:
                        print(f"[TigerOptionClient] All {len(hk_symbols)} HK stock names found in cache")
                    
                    # 构建持仓对象
                    for symbol, pos in hk_position_map.items():
                        quantity = int(pos.quantity or 0)
                        
                        # 尝试获取股票名称（优先从contract，其次从缓存/API）
                        stock_name = None
                        if hasattr(pos.contract, 'name') and pos.contract.name:
                            stock_name = pos.contract.name
                        elif hasattr(pos.contract, 'local_symbol') and pos.contract.local_symbol:
                            stock_name = pos.contract.local_symbol
                        elif symbol in stock_names:
                            stock_name = stock_names[symbol]
                        
                        print(f"[TigerOptionClient] HK Position: {symbol} ({stock_name}), qty={quantity}")
                        
                        underlying = UnderlyingPosition(
                            symbol=symbol,
                            market="HK",
                            quantity=quantity,
                            avg_price=float(pos.average_cost or 0),
                            last_price=float(pos.market_price or 0),
                            currency=pos.contract.currency or "HKD",
                            name=stock_name,
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
                market=Market.US,
                account=account_id
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
                    err_str = str(e)
                    if "permission denied" in err_str.lower() or "rate limit" in err_str.lower():
                        print(f"[TigerOptionClient] Option quote permission not available, using default greeks. {e}")
                    else:
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
                    last_price = float(getattr(brief, 'latest_price', getattr(pos, 'market_price', 0)))
                else:
                    # 如果没有行情数据，使用默认值
                    greeks = Greeks(delta=0, gamma=0, vega=0, theta=0)
                    # 对于期权仓位，pos.market_price 是期权的价格，而非标的价格
                    last_price = float(getattr(pos, 'market_price', 0))
                    # 尝试从 pos 获取标的价格（如果 SDK 提供）
                    underlying_price = float(getattr(pos, 'underlying_price', last_price))

                option_pos = OptionPosition(
                    contract=contract,
                    quantity=int(pos.quantity or 0),
                    avg_price=float(pos.average_cost or 0),
                    last_price=last_price,
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

    async def place_order(self, account_id: str, order_params: dict) -> dict:
        """真实下单到老虎证券"""
        symbol = order_params.get("symbol")
        direction = order_params.get("direction")  # LONG / SHORT
        quantity = order_params.get("quantity")
        price = order_params.get("price")
        order_type = order_params.get("order_type", "LIMIT")
        
        # 映射方向 (tigeropen SDK 在不同版本中可能没有 Action enum,
        # 我们使用字符串 'BUY'/'SELL' 以保持兼容性；具体下单构造会根据 SDK 要求转换)
        action = 'BUY' if direction == "LONG" else 'SELL'
        
        try:
            # 将通用 order_type 映射为 tigeropen SDK 接受的简写类型
            mapping = {
                "LIMIT": "LMT",
                "MARKET": "MKT",
                "LIMIT_ON_CLOSE": "LMT",
                "MARKET_ON_CLOSE": "MKT",
                "STOP_LIMIT": "STP_LMT",
                "STOP": "STP",
            }
            order_type_upper = (order_type or "").upper()
            sdk_order_type = mapping.get(order_type_upper, order_type_upper)

            print(f"[TigerOptionClient] Placing {sdk_order_type} order for {symbol}: {action} {quantity} @ {price}")
            
            # 1. 创建订单对象
            # 注意: tigeropen API 创建订单通常使用 TradeClient.create_order
            # 获取合约信息可能需要, 但对于简单股票可以直接创建
            contract = await self._run_in_executor(
                self.trade_client.get_contracts,
                symbol,
                SecurityType.STK
            )
            
            if not contract:
                return {"success": False, "message": f"Could not find contract for {symbol}"}
            
            # 2. 构造订单
            # tigeropen SDK 示例通常是:
            # order = Order(account, contract[0], action, order_type, quantity, limit_price=price)
            # 构造 tiger SDK 期望的 Order 对象，使用映射后的 order_type
            # 对价位进行 tick 对齐（Tiger 要求 price 必须是 tick 的整数倍）
            limit_price = price if sdk_order_type in ("LMT",) else None
            if limit_price is not None:
                # 先尝试从合约对象获取最小价格增量字段
                tick = None
                try:
                    possible_attrs = ['tick_size', 'min_price_increment', 'min_tick', 'price_tick']
                    for a in possible_attrs:
                        if hasattr(contract[0], a):
                            tick = getattr(contract[0], a)
                            break
                except Exception:
                    tick = None

                try:
                    tick = float(tick) if tick else 0.01
                except Exception:
                    tick = 0.01

                # 使用 Decimal 精确对齐：买单向下取整，卖单向上取整，避免被拒绝
                d_price = Decimal(str(limit_price))
                d_tick = Decimal(str(tick))
                if action == 'BUY':
                    aligned = (d_price / d_tick).quantize(Decimal('1'), rounding=ROUND_FLOOR) * d_tick
                else:
                    aligned = (d_price / d_tick).quantize(Decimal('1'), rounding=ROUND_CEILING) * d_tick

                # 防止对齐后为 0
                if aligned <= Decimal('0'):
                    aligned = d_tick

                aligned_price = float(aligned)
                if aligned_price != limit_price:
                    print(f"[TigerOptionClient] Aligning price {limit_price} -> {aligned_price} using tick {tick}")
                limit_price = aligned_price
            tiger_order = Order(
                account_id,
                contract[0],
                action,
                sdk_order_type,
                quantity,
                limit_price=limit_price
            )
            
            # 3. 提交订单
            order_id = await self._run_in_executor(
                self.trade_client.place_order,
                tiger_order
            )
            
            if order_id:
                print(f"[TigerOptionClient] Order placed successfully, id: {order_id}")
                return {
                    "success": True,
                    "order_id": str(order_id),
                    "ext_order_id": str(order_id),
                    "status": "SUBMITTED",
                    "executed_price": limit_price if sdk_order_type == "LMT" else price,
                    "executed_quantity": quantity,
                    "message": "Order submitted to Tiger successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to get order_id from Tiger"
                }
                
        except Exception as e:
            print(f"[TigerOptionClient] Place order failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"Tiger API error: {str(e)}"
            }

    async def get_order_status(self, account_id: str, order_id: str) -> dict:
        """获取老虎证券订单状态"""
        try:
            # 兼容性处理：当前版本的 get_orders 不支持直接传 id 参数
            # 我们获取最近的订单列表并在本地过滤
            orders = await self._run_in_executor(
                self.trade_client.get_orders,
                account=account_id,
                limit=50  # 获取最近50笔，覆盖当前活跃订单
            )
            
            if not orders:
                print(f"[TigerOptionClient] No orders returned for account {account_id}")
                return {"status": "NOT_FOUND", "message": "No orders found"}
            
            # 本地按 ID 过滤
            target_order = None
            search_ids = [str(order_id)]
            print(f"[TigerOptionClient] Searching for order_id: {order_id} in {len(orders)} recent orders")
            
            for o in orders:
                # Tiger SDK 的 Order 对象通常有 id 和 order_id，且可能包含外部 ID
                # 我们同时检查并打印前几个订单的 ID 结构以便调试
                o_id = str(getattr(o, 'id', ''))
                o_order_id = str(getattr(o, 'order_id', ''))
                
                if o_id in search_ids or o_order_id in search_ids:
                    target_order = o
                    break
            
            if not target_order:
                # 记录调试信息：打印最近三个订单的 ID
                debug_info = []
                for o in orders[:3]:
                    debug_info.append(f"id={getattr(o,'id','?')}, order_id={getattr(o,'order_id','?')}")
                print(f"[TigerOptionClient] Order {order_id} not found. Recent orders: {', '.join(debug_info)}")
                return {"status": "NOT_FOUND", "message": "Order not found in recent history"}
            
            status = target_order.status
            
            # 映射 Tiger 状态到内部通用状态
            # Tiger OrderStatus: PENDING_NEW, NEW, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED, INACTIVE
            status_map = {
                OrderStatus.FILLED: "FILLED",
                OrderStatus.CANCELLED: "CANCELLED",
                OrderStatus.REJECTED: "REJECTED",
                OrderStatus.EXPIRED: "CANCELLED",
                OrderStatus.PARTIALLY_FILLED: "EXECUTING",
                OrderStatus.NEW: "PENDING",
                OrderStatus.PENDING_NEW: "PENDING",
            }
            
            internal_status = status_map.get(status, "EXECUTING")
            
            # 获取原因消息（如资金不足）
            reason = getattr(target_order, 'reason', '')
            if not reason and hasattr(target_order, 'status_msg') and target_order.status_msg:
                reason = target_order.status_msg
            if not reason and hasattr(target_order, 'attr_desc') and target_order.attr_desc:
                reason = target_order.attr_desc
            
            # 如果是撤单状态，补充一个描述
            if internal_status == "CANCELLED" and not reason:
                reason = "订单已被系统或用户撤销"
            elif internal_status == "REJECTED" and not reason:
                reason = "订单被券商拒绝"
            
            return {
                "status": internal_status,
                "filled_quantity": float(getattr(target_order, 'filled_quantity', 0)),
                "avg_fill_price": float(getattr(target_order, 'avg_fill_price', 0)),
                "message": reason or (status.name if hasattr(status, 'name') else str(status))
            }
            
        except Exception as e:
            print(f"[TigerOptionClient] Error getting order status: {e}")
            return {"status": "ERROR", "message": str(e)}
