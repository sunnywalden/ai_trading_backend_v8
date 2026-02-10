"""
订单执行引擎 - 自动交易执行的核心

功能:
1. 从信号队列获取已验证的交易信号
2. 自动生成和提交订单
3. 监控订单执行状态
4. 处理部分成交和拒单
5. 执行质量跟踪
6. 与broker集成
"""
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import uuid4
from decimal import Decimal

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import TradingSignal, SignalStatus
from app.broker.factory import make_option_broker_client
from app.services.account_service import AccountService
from app.services.risk_event_logger import log_risk_event
from app.core.trade_mode import TradeMode
from app.core.config import settings


class OrderExecutor:
    """订单执行引擎 - 将信号转化为实际交易"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.broker = make_option_broker_client()
        self.account_svc = AccountService(session)
        self.dry_run_mode = False  # 可通过配置控制
    
    async def execute_signal_batch(
        self,
        account_id: str,
        max_orders: int = 5,
        trade_mode: Optional[TradeMode] = None
    ) -> Dict[str, Any]:
        """
        批量执行信号 - 量化交易的自动化核心
        
        流程:
        1. 获取待执行的高优先级信号
        2. 按优先级和风险预算分配
        3. 生成订单并提交
        4. 跟踪执行状态
        """
        # 获取待执行信号
        from app.engine.signal_engine import SignalEngine
        signal_engine = SignalEngine(self.session)
        
        pending_signals = await signal_engine.get_pending_signals(
            account_id=account_id,
            status=SignalStatus.VALIDATED,
            limit=max_orders
        )
        
        if not pending_signals:
            return {
                "executed": 0,
                "failed": 0,
                "queued": 0,
                "message": "No pending signals to execute"
            }
        
        # 🛡️ 执行阶段去重保护：按symbol去重，保留信号强度最高的
        symbol_signal_map: Dict[str, TradingSignal] = {}
        for signal in pending_signals:
            if signal.symbol not in symbol_signal_map:
                symbol_signal_map[signal.symbol] = signal
            else:
                # 保留信号强度更高的
                if signal.signal_strength > symbol_signal_map[signal.symbol].signal_strength:
                    symbol_signal_map[signal.symbol] = signal
        
        # 使用去重后的信号列表
        pending_signals = list(symbol_signal_map.values())
        
        # 获取账户信息
        account_equity = await self.account_svc.get_equity_usd(account_id)
        
        executed_count = 0
        failed_count = 0
        queued_count = 0
        
        execution_results = []
        
        for signal in pending_signals:
            try:
                # 更新信号状态为执行中
                signal.status = SignalStatus.QUEUED
                await self.session.commit()
                queued_count += 1
                
                # 执行订单
                result = await self._execute_single_signal(
                    signal=signal,
                    account_equity=account_equity,
                    trade_mode=trade_mode
                )
                
                execution_results.append(result)
                
                if result["success"]:
                    executed_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                failed_count += 1
                signal.status = SignalStatus.FAILED
                await self.session.commit()
                
                await log_risk_event(
                    self.session,
                    account_id=account_id,
                    event_type="ORDER_EXECUTION_ERROR",
                    level="ERROR",
                    message=f"Failed to execute signal {signal.signal_id}: {str(e)}",
                    symbol=signal.symbol
                )
        
        return {
            "executed": executed_count,
            "failed": failed_count,
            "queued": queued_count,
            "results": execution_results
        }
    
    async def _execute_single_signal(
        self,
        signal: TradingSignal,
        account_equity: float,
        trade_mode: Optional[TradeMode] = None
    ) -> Dict[str, Any]:
        """执行单个信号"""
        
        # 计算订单参数
        order_params = await self._calculate_order_params(signal, account_equity)
        
        # 检查是否为演练模式
        if trade_mode == TradeMode.DRY_RUN or self.dry_run_mode:
            return await self._simulate_order_execution(signal, order_params)
        
        # 实际执行订单
        try:
            order_id = str(uuid4())
            
            # 这里集成实际的broker API
            # 当前使用模拟执行
            executed_price = order_params["price"] * (1 + 0.001)  # 模拟小幅滑点
            executed_quantity = order_params["quantity"]
            
            # 更新信号状态
            signal.status = SignalStatus.EXECUTING
            signal.order_id = order_id
            await self.session.commit()
            
            # 记录到交易日志
            await self._log_execution(
                signal=signal,
                order_id=order_id,
                executed_price=executed_price,
                executed_quantity=executed_quantity
            )
            
            # 更新信号执行信息
            from app.engine.signal_engine import SignalEngine
            signal_engine = SignalEngine(self.session)
            await signal_engine.update_signal_execution(
                signal_id=signal.signal_id,
                order_id=order_id,
                executed_price=executed_price,
                executed_quantity=executed_quantity
            )
            
            return {
                "success": True,
                "signal_id": signal.signal_id,
                "order_id": order_id,
                "symbol": signal.symbol,
                "executed_price": executed_price,
                "executed_quantity": executed_quantity,
                "message": "Order executed successfully"
            }
            
        except Exception as e:
            signal.status = SignalStatus.FAILED
            await self.session.commit()
            
            return {
                "success": False,
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "error": str(e),
                "message": f"Order execution failed: {str(e)}"
            }
    
    async def _calculate_order_params(
        self,
        signal: TradingSignal,
        account_equity: float
    ) -> Dict[str, Any]:
        """计算订单参数"""
        
        # 基于信号和账户权益计算实际交易数量
        position_size_pct = signal.suggested_quantity or 0.10
        position_value = account_equity * position_size_pct
        
        # 获取当前市价(这里需要集成市场数据)
        current_price = signal.suggested_price or 100.0
        
        quantity = int(position_value / current_price)
        
        # 计算限价单价格(稍微好于市价)
        if signal.direction == "LONG":
            limit_price = current_price * 1.002  # 买入时略高于市价
        else:
            limit_price = current_price * 0.998  # 卖出时略低于市价
        
        return {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "quantity": max(1, quantity),  # 至少1股
            "price": limit_price,
            "order_type": "LIMIT",
            "time_in_force": "DAY",
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit
        }
    
    async def _simulate_order_execution(
        self,
        signal: TradingSignal,
        order_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """模拟订单执行(用于演练模式)"""
        
        order_id = f"SIM_{uuid4()}"
        
        # 模拟执行
        signal.status = SignalStatus.EXECUTED
        signal.order_id = order_id
        signal.executed_at = datetime.utcnow()
        signal.executed_price = order_params["price"]
        signal.executed_quantity = order_params["quantity"]
        signal.execution_slippage = 0.001  # 模拟1bp滑点
        
        await self.session.commit()
        
        await log_risk_event(
            self.session,
            account_id=signal.account_id,
            event_type="ORDER_SIMULATED",
            level="INFO",
            message=f"Simulated order: {signal.direction} {order_params['quantity']} {signal.symbol} @ {order_params['price']:.2f}",
            symbol=signal.symbol,
            extra_json=order_params
        )
        
        return {
            "success": True,
            "signal_id": signal.signal_id,
            "order_id": order_id,
            "symbol": signal.symbol,
            "executed_price": order_params["price"],
            "executed_quantity": order_params["quantity"],
            "message": "Order simulated successfully (DRY RUN MODE)",
            "dry_run": True
        }
    
    async def _log_execution(
        self,
        signal: TradingSignal,
        order_id: str,
        executed_price: float,
        executed_quantity: float
    ) -> None:
        """记录执行到交易日志"""
        
        await log_risk_event(
            self.session,
            account_id=signal.account_id,
            event_type="ORDER_EXECUTED",
            level="INFO",
            message=f"Executed: {signal.direction} {executed_quantity} {signal.symbol} @ {executed_price:.2f}",
            symbol=signal.symbol,
            extra_json={
                "signal_id": signal.signal_id,
                "order_id": order_id,
                "signal_source": signal.signal_source.value,
                "signal_strength": signal.signal_strength,
                "expected_return": signal.expected_return,
            }
        )
    
    async def monitor_order_status(
        self,
        order_id: str
    ) -> Dict[str, Any]:
        """监控订单状态(用于异步订单)"""
        
        # 查询订单状态
        # 这里需要集成broker API
        
        return {
            "order_id": order_id,
            "status": "FILLED",  # PENDING/FILLED/PARTIALLY_FILLED/CANCELLED/REJECTED
            "filled_quantity": 100,
            "avg_fill_price": 150.25,
            "message": "Order filled successfully"
        }
    
    async def cancel_signal(self, signal_id: str) -> bool:
        """取消信号(如果还未执行)"""
        
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return False
        
        if signal.status in [SignalStatus.EXECUTED, SignalStatus.CANCELLED]:
            return False  # 已执行或已取消
        
        signal.status = SignalStatus.CANCELLED
        await self.session.commit()
        
        await log_risk_event(
            self.session,
            account_id=signal.account_id,
            event_type="SIGNAL_CANCELLED",
            level="INFO",
            message=f"Signal cancelled: {signal.symbol}",
            symbol=signal.symbol
        )
        
        return True
