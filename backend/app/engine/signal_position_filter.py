"""
信号持仓过滤器 - 根据当前持仓过滤交易信号

功能:
1. 获取当前账户持仓信息
2. 根据信号类型和持仓状态过滤无效信号
3. 提供详细的过滤统计和原因
"""
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import TradingSignal, SignalType, SignalStatus
from app.broker.factory import make_option_broker_client
from app.services.account_service import AccountService
from app.providers.market_data_provider import MarketDataProvider


@dataclass
class FilterResult:
    """过滤结果"""
    passed: bool
    reason: str = ""


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    qty: float  # 正数=多头，负数=空头
    avg_cost: float
    market_value: float
    unrealized_pnl: float


class SignalPositionFilter:
    """信号与持仓联动过滤器"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        try:
            self.broker = make_option_broker_client()
        except Exception as e:
            print(f"初始化broker失败: {e}")
            self.broker = None
        self.account_svc = AccountService(session, self.broker)
        self.market_provider = MarketDataProvider()
    
    async def filter_signals_with_positions(
        self,
        signals: List[TradingSignal],
        account_id: str
    ) -> Tuple[List[TradingSignal], Dict]:
        """
        根据当前持仓过滤信号 (包含港股碎股检查)
        
        Returns:
            - filtered_signals: 过滤后的有效信号列表
            - filter_stats: 过滤统计
        """
        # 1. 获取当前所有持仓
        positions = await self._get_current_positions(account_id)
        # 统一标的代码格式为大写并去空格，防止匹配失败
        position_map = {p.symbol.strip().upper(): p for p in positions if p.symbol}
        
        # 2. 获取账户权益（用于计算港股数量是否合规）
        account_equity = await self.account_svc.get_equity_usd(account_id)
        
        print(f"[SignalPositionFilter] Fetched {len(positions)} positions and {account_equity:.2f} equity for account {account_id}")
        if positions:
            print(f"[SignalPositionFilter] Position symbols: {list(position_map.keys())}")
        
        # 3. 逐个过滤信号
        filtered_signals = []
        filter_stats = {
            "total": len(signals),
            "filtered_out": 0,
            "passed": 0,
            "reasons": {}
        }
        
        for signal in signals:
            symbol_key = signal.symbol.strip().upper()
            print(f"[SignalPositionFilter] Checking signal: {signal.symbol} ({signal.signal_type.value} {signal.direction}) against account {account_id}")
            
            # --- 3.1 原有持仓过滤逻辑 ---
            filter_result = self._filter_single_signal(signal, position_map)
            
            # --- 3.2 港股碎股/LotSize过滤逻辑 ---
            if filter_result.passed and signal.symbol.endswith(".HK"):
                hk_lot_result = await self._check_hk_lot_size(signal, account_equity)
                if not hk_lot_result.passed:
                    filter_result = hk_lot_result
            
            if filter_result.passed:
                # 添加当前持仓信息到信号元数据
                if symbol_key in position_map:
                    if not signal.extra_metadata:
                        signal.extra_metadata = {}
                    position = position_map[symbol_key]
                    signal.extra_metadata["current_position"] = {
                        "qty": position.qty,
                        "avg_cost": position.avg_cost,
                        "market_value": position.market_value,
                        "unrealized_pnl": position.unrealized_pnl
                    }
                    print(f"[SignalPositionFilter] Signal {signal.symbol} passed, added position info")
                
                filtered_signals.append(signal)
                filter_stats["passed"] += 1
            else:
                filter_stats["filtered_out"] += 1
                reason = filter_result.reason
                filter_stats["reasons"][reason] = filter_stats["reasons"].get(reason, 0) + 1
                
                print(f"[SignalPositionFilter] Signal {signal.symbol} filtered out: {reason}")
                
                # 更新信号状态
                signal.status = SignalStatus.EXPIRED
                if not signal.extra_metadata:
                    signal.extra_metadata = {}
                signal.extra_metadata["filter_reason"] = reason
                signal.extra_metadata["filtered_at"] = datetime.utcnow().isoformat()
        
        # 只有在有信号被过滤时才提交
        if filter_stats["filtered_out"] > 0:
            try:
                await self.session.commit()
            except Exception as e:
                print(f"[SignalPositionFilter] Error committing expired signals: {e}")
        
        return filtered_signals, filter_stats

    async def _check_hk_lot_size(self, signal: TradingSignal, account_equity: float) -> FilterResult:
        """检查港股数量是否满足一手 (Lot Size) 限制"""
        try:
            # 1. 获取该股票的一手数量 (Lot Size)
            lot_size = await self.market_provider.get_lot_size(signal.symbol)
            if lot_size <= 1:
                return FilterResult(passed=True)
            
            # 2. 计算预计交易数量
            # 参考 OrderExecutor._calculate_order_params 的逻辑
            pos_pct = signal.suggested_quantity or 0.10
            pos_value = account_equity * pos_pct
            
            # 获取价格
            price = signal.suggested_price or await self.market_provider.get_current_price(signal.symbol)
            if not price or price <= 0:
                print(f"[SignalPositionFilter] Skip lot size check for {signal.symbol} due to missing price")
                return FilterResult(passed=True)
            
            total_qty = int(pos_value / price)
            
            # 3. 校验
            if total_qty < lot_size:
                return FilterResult(
                    passed=False, 
                    reason=f"数量不足一手 (港股限制): 预计{total_qty}股, 最小单位{lot_size}股"
                )
            
            return FilterResult(passed=True)
            
        except Exception as e:
            print(f"[SignalPositionFilter] Error checking HK lot size for {signal.symbol}: {e}")
            return FilterResult(passed=True)

    async def _get_current_positions(self, account_id: str) -> List[Position]:
        """获取当前持仓"""
        if not self.broker:
            print("[SignalPositionFilter] Broker not initialized, returning empty positions")
            return []
        
        try:
            # 调用broker获取持仓 (美股/港股标底)
            # 确保传入了 account_id
            print(f"[SignalPositionFilter] Requesting positions for account: {account_id}")
            results = await self.broker.list_underlying_positions(account_id)
            
            positions = []
            for pos_data in results:
                # 处理 UnderlyingPosition 对象
                # 兼容不同来源的数据格式
                symbol = getattr(pos_data, 'symbol', None)
                if not symbol:
                    continue
                
                qty = getattr(pos_data, 'quantity', 0)
                avg_price = getattr(pos_data, 'avg_price', 0)
                last_price = getattr(pos_data, 'last_price', 0)
                
                position = Position(
                    symbol=str(symbol),
                    qty=float(qty),
                    avg_cost=float(avg_price),
                    market_value=float(qty * last_price),
                    unrealized_pnl=float(qty * (last_price - avg_price))
                )
                positions.append(position)
            
            return positions
        except Exception as e:
            import traceback
            print(f"[SignalPositionFilter] Error getting positions: {e}")
            traceback.print_exc()
            return []

    def _filter_single_signal(
        self, 
        signal: TradingSignal, 
        position_map: Dict[str, Position]
    ) -> FilterResult:
        """单个信号过滤逻辑"""
        
        symbol_key = signal.symbol.strip().upper()
        current_position = position_map.get(symbol_key)
        
        # 开仓信号过滤
        if signal.signal_type == SignalType.ENTRY:
            return self._filter_entry_signal(signal, current_position)
        
        # 平仓信号过滤
        elif signal.signal_type == SignalType.EXIT:
            return self._filter_exit_signal(signal, current_position)
        
        # 加仓信号过滤
        elif signal.signal_type == SignalType.ADD:
            return self._filter_add_signal(signal, current_position)
        
        # 减仓信号过滤
        elif signal.signal_type == SignalType.REDUCE:
            return self._filter_reduce_signal(signal, current_position)
        
        # 对冲信号默认通过
        return FilterResult(passed=True)
    
    def _filter_entry_signal(
        self, 
        signal: TradingSignal, 
        current_position: Optional[Position]
    ) -> FilterResult:
        """开仓信号过滤"""
        
        if not current_position:
            # 无持仓，可以开仓
            return FilterResult(passed=True)
        
        # 多头开仓：检查是否已有足够多头
        if signal.direction == "LONG":
            if current_position.qty >= signal.suggested_quantity:
                return FilterResult(
                    passed=False,
                    reason=f"已有多头持仓{current_position.qty:.0f}，大于等于建议数量{signal.suggested_quantity:.0f}"
                )
        
        # 空头开仓：检查是否已有足够空头
        elif signal.direction == "SHORT":
            if current_position.qty <= -signal.suggested_quantity:
                return FilterResult(
                    passed=False,
                    reason=f"已有空头持仓{abs(current_position.qty):.0f}，大于等于建议数量{signal.suggested_quantity:.0f}"
                )
        
        return FilterResult(passed=True)
    
    def _filter_exit_signal(
        self, 
        signal: TradingSignal, 
        current_position: Optional[Position]
    ) -> FilterResult:
        """平仓信号过滤"""
        
        # 无持仓，无法平仓
        if not current_position or abs(current_position.qty) < 0.01:
            return FilterResult(
                passed=False,
                reason=f"当前无{signal.symbol}持仓，无需平仓"
            )
        
        # 检查持仓方向与平仓方向是否匹配
        if signal.direction == "LONG" and current_position.qty <= 0:
            return FilterResult(
                passed=False,
                reason="当前持有空仓，无法平多仓"
            )
        
        if signal.direction == "SHORT" and current_position.qty >= 0:
            return FilterResult(
                passed=False,
                reason="当前持有多仓，无法平空仓"
            )
        
        return FilterResult(passed=True)
    
    def _filter_add_signal(
        self, 
        signal: TradingSignal, 
        current_position: Optional[Position]
    ) -> FilterResult:
        """加仓信号过滤"""
        
        # 无基础持仓，无法加仓
        if not current_position or abs(current_position.qty) < 0.01:
            return FilterResult(
                passed=False,
                reason="无基础持仓，无法加仓（可转为开仓信号）"
            )
        
        # 检查加仓方向与持仓方向是否一致
        if signal.direction == "LONG" and current_position.qty <= 0:
            return FilterResult(
                passed=False,
                reason="当前持有空仓，无法加多仓"
            )
        
        if signal.direction == "SHORT" and current_position.qty >= 0:
            return FilterResult(
                passed=False,
                reason="当前持有多仓，无法加空仓"
            )
        
        return FilterResult(passed=True)
    
    def _filter_reduce_signal(
        self, 
        signal: TradingSignal, 
        current_position: Optional[Position]
    ) -> FilterResult:
        """减仓信号过滤"""
        
        # 无持仓，无法减仓
        if not current_position or abs(current_position.qty) < 0.01:
            return FilterResult(
                passed=False,
                reason="无持仓，无法减仓"
            )
        
        # 检查减仓数量是否超过持仓
        if abs(current_position.qty) < signal.suggested_quantity:
            return FilterResult(
                passed=False,
                reason=f"减仓数量{signal.suggested_quantity:.0f}超过持仓{abs(current_position.qty):.0f}（可转为平仓）"
            )
        
        return FilterResult(passed=True)
