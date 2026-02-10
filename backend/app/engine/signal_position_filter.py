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
        self.account_svc = AccountService(session)
    
    async def filter_signals_with_positions(
        self,
        signals: List[TradingSignal],
        account_id: str
    ) -> Tuple[List[TradingSignal], Dict]:
        """
        根据当前持仓过滤信号
        
        Returns:
            - filtered_signals: 过滤后的有效信号列表
            - filter_stats: 过滤统计
        """
        # 1. 获取当前所有持仓
        positions = await self._get_current_positions(account_id)
        position_map = {p.symbol: p for p in positions}
        
        # 2. 逐个过滤信号
        filtered_signals = []
        filter_stats = {
            "total": len(signals),
            "filtered_out": 0,
            "passed": 0,
            "reasons": {}
        }
        
        for signal in signals:
            filter_result = self._filter_single_signal(signal, position_map)
            
            if filter_result.passed:
                # 添加当前持仓信息到信号元数据
                if signal.symbol in position_map:
                    if not signal.extra_metadata:
                        signal.extra_metadata = {}
                    position = position_map[signal.symbol]
                    signal.extra_metadata["current_position"] = {
                        "qty": position.qty,
                        "avg_cost": position.avg_cost,
                        "market_value": position.market_value,
                        "unrealized_pnl": position.unrealized_pnl
                    }
                
                filtered_signals.append(signal)
                filter_stats["passed"] += 1
            else:
                filter_stats["filtered_out"] += 1
                reason = filter_result.reason
                filter_stats["reasons"][reason] = filter_stats["reasons"].get(reason, 0) + 1
                
                # 更新信号状态
                signal.status = SignalStatus.EXPIRED
                if not signal.extra_metadata:
                    signal.extra_metadata = {}
                signal.extra_metadata["filter_reason"] = reason
                signal.extra_metadata["filtered_at"] = datetime.utcnow().isoformat()
        
        # 只有在有信号被过滤时才提交
        if filter_stats["filtered_out"] > 0:
            await self.session.commit()
        
        return filtered_signals, filter_stats
    
    async def _get_current_positions(self, account_id: str) -> List[Position]:
        """获取当前持仓（简化版 - 实际应调用broker API）"""
        # TODO: 集成实际的broker API
        # 目前返回空列表，后续可以接入真实持仓数据
        
        if not self.broker:
            return []
        
        try:
            # 调用broker获取持仓 (美股/港股标底)
            results = await self.broker.list_underlying_positions(account_id)
            
            positions = []
            for pos_data in results:
                # 处理 UnderlyingPosition 对象
                qty = getattr(pos_data, 'quantity', 0)
                avg_price = getattr(pos_data, 'avg_price', 0)
                last_price = getattr(pos_data, 'last_price', 0)
                
                position = Position(
                    symbol=getattr(pos_data, 'symbol', ''),
                    qty=float(qty),
                    avg_cost=float(avg_price),
                    market_value=float(qty * last_price),
                    unrealized_pnl=float(qty * (last_price - avg_price))
                )
                positions.append(position)
            
            return positions
        except Exception as e:
            import traceback
            print(f"获取持仓失败: {e}")
            traceback.print_exc()
            return []
    
    def _filter_single_signal(
        self, 
        signal: TradingSignal, 
        position_map: Dict[str, Position]
    ) -> FilterResult:
        """单个信号过滤逻辑"""
        
        current_position = position_map.get(signal.symbol)
        
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
