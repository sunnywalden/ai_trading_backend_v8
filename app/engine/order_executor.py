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
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.config import settings
from app.core.trade_mode import TradeMode
from app.models.execution_slice import ExecutionSlice, SliceStatus
from app.models.trading_signal import SignalStatus, SignalType, TradingSignal
from app.providers.market_data_provider import MarketDataProvider
from app.services.account_service import AccountService
from app.services.risk_event_logger import log_risk_event

logger = logging.getLogger(__name__)


class OrderExecutor:
    """订单执行引擎 - 将信号转化为实际交易"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.broker = make_option_broker_client()
        self.account_svc = AccountService(session, self.broker)
        self.market_provider = MarketDataProvider()
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
                # 保持 VALIDATED 状态，以便在待执行列表中保留
                signal.status = SignalStatus.VALIDATED
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
            # 🚀 集成实际的券商 API 下单
            print(f"[OrderExecutor] Calling broker.place_order for {signal.symbol}")
            resp = await self.broker.place_order(signal.account_id, order_params)
            
            if not resp.get("success"):
                error_msg = resp.get("message", "Unknown broker error")
                print(f"[OrderExecutor] Broker placement failed: {error_msg}")
                raise Exception(error_msg)
            
            order_id = resp.get("order_id")
            if not order_id:
                raise Exception("Broker did not return a valid order_id")
            order_id = str(order_id)
            # 优先使用券商返回的实际委托参数（可能经过了精度对齐）
            executed_price = resp.get("executed_price", order_params["price"])
            executed_quantity = resp.get("executed_quantity", order_params["quantity"])
            
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
            
            # 🔍 下单后延迟检查：等待3秒后验证券商的最终状态
            # 避免订单因资金不足等原因被撤销但系统未感知
            print(f"[OrderExecutor] Waiting 3s to verify final order status for {order_id}...")
            await asyncio.sleep(3)
            status_check = await self.monitor_order_status(signal.account_id, order_id)
            
            # 如果券商已撤销或拒绝订单，返回失败
            if status_check.get("status") in ["CANCELLED", "REJECTED"]:
                error_reason = status_check.get("message", "券商撤销订单")
                print(f"[OrderExecutor] Order {order_id} was cancelled/rejected: {error_reason}")
                return {
                    "success": False,
                    "signal_id": signal.signal_id,
                    "order_id": order_id,
                    "symbol": signal.symbol,
                    "error": error_reason,
                    "message": f"订单被撤销: {error_reason}"
                }
            
            return {
                "success": True,
                "signal_id": signal.signal_id,
                "order_id": order_id,
                "symbol": signal.symbol,
                "executed_price": executed_price,
                "executed_quantity": executed_quantity,
                "message": resp.get("message", "Order executed successfully via Broker")
            }
            
        except Exception as e:
            # 保持 VALIDATED 状态，以便在待执行列表中保留
            signal.status = SignalStatus.VALIDATED
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
        """计算订单参数 (包含碎股/一手限制逻辑)"""
        signal_meta = signal.extra_metadata or {}
        current_position = signal_meta.get("current_position") or {}
        current_position_qty = abs(float(current_position.get("qty") or 0))
        is_closing_signal = signal.signal_type in {SignalType.EXIT, SignalType.REDUCE}
        execution_direction = signal.direction
        if is_closing_signal:
            execution_direction = "SHORT" if signal.direction == "LONG" else "LONG"
        
        # 1. 确定价格和订单类型
        # 如果建议价格为空，认为是市价单
        is_market_order = signal.suggested_price is None or signal.suggested_price <= 0
        
        # 获取当前市价
        current_price = signal.suggested_price or await self.market_provider.get_current_price(signal.symbol)
        if not current_price or current_price <= 0:
            current_price = 100.0  # 安全回退值
        
        # 2. 计算实际交易数量
        # 💡 这里解决一个关键的歧义：suggested_quantity 是股份单位还是比例？
        # 如果大于 1.0，认为是绝对股数（由 QuickTrade 发起）；如果小于 1.0，认为是账户占比（由量化策略发起）
        quantity = 0
        if is_closing_signal and current_position_qty > 0:
            if signal.signal_type == SignalType.EXIT:
                quantity = int(round(current_position_qty))
                print(f"[OrderExecutor] Using actual position qty for EXIT: {quantity}")
            else:
                requested_qty = float(signal.quantity_value or signal.suggested_quantity or 0)
                if requested_qty <= 0:
                    requested_qty = current_position_qty * 0.3
                elif requested_qty < 1.0:
                    requested_qty = current_position_qty * requested_qty
                quantity = int(round(min(requested_qty, current_position_qty)))
                print(f"[OrderExecutor] Using adjusted REDUCE qty: {quantity} (held={current_position_qty})")
        elif signal.suggested_quantity and signal.suggested_quantity >= 1.0:
            # 认为是绝对股数
            quantity = int(signal.suggested_quantity)
            print(f"[OrderExecutor] Using absolute quantity from signal: {quantity}")
        else:
            # 认为是账户占比 (如果为空则默认为 10%)
            position_size_pct = signal.suggested_quantity if (signal.suggested_quantity and signal.suggested_quantity > 0) else 0.10
            position_value = account_equity * position_size_pct
            quantity = int(position_value / current_price)
            print(f"[OrderExecutor] Calculated quantity from account ratio ({position_size_pct:.2%}): {quantity}")
        
        # --- 港股一手限制处理 ---
        if signal.symbol.endswith(".HK") and not is_closing_signal:
            lot_size = await self.market_provider.get_lot_size(signal.symbol)
            if lot_size > 1:
                # 向下取整到 lot_size 的倍数
                original_qty = quantity
                quantity = (quantity // lot_size) * lot_size
                print(f"[OrderExecutor] HK Stock {signal.symbol} lot size adjustment: {original_qty} -> {quantity} (lot_size={lot_size})")
                
                if quantity < lot_size:
                    raise ValueError(f"港股数量不足一手: 预计{original_qty}股, 最小单位{lot_size}股, 调整后数量为0")

        # 3. 确定订单指令和价格
        if is_market_order:
            # 市价单：不传限价，类型为 MARKET
            order_type = "MARKET"
            limit_price = None
            print(f"[OrderExecutor] Preparing MARKET order for {signal.symbol}")
        else:
            # 限价单：优化价格策略 (买入时略高于市价，卖出时略低于市价，提高成交率)
            order_type = "LIMIT"
            if execution_direction == "LONG":
                limit_price = current_price * 1.002  # 买入时略高于市价
            else:
                limit_price = current_price * 0.998  # 卖出时略低于市价
            print(f"[OrderExecutor] Preparing LIMIT order for {signal.symbol} at {limit_price:.2f}")
        
        return {
            "symbol": signal.symbol,
            "direction": execution_direction,
            "quantity": max(1, quantity),  # 至少1股
            "price": limit_price,
            "order_type": order_type,
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
        
        # 1. 记录到风险事件日志 (System Event)
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

        # 2. 记录到交易日志 (Trade Journal - 供前端展示和复盘)
        try:
            from app.services.journal_service import JournalService
            journal_svc = JournalService(self.session)
            await journal_svc.create_from_execution(
                account_id=signal.account_id,
                symbol=signal.symbol,
                direction=signal.direction,
                price=executed_price,
                quantity=executed_quantity,
                signal_id=signal.signal_id
            )
        except Exception as e:
            print(f"[OrderExecutor] Failed to create journal entry: {e}")

    @staticmethod
    def _resolve_execution_side(signal: TradingSignal) -> str:
        direction = str(signal.direction or "LONG").upper()
        if signal.signal_type in {SignalType.EXIT, SignalType.REDUCE}:
            return "SELL" if direction == "LONG" else "BUY"
        return "BUY" if direction in {"LONG", "BUY"} else "SELL"

    @staticmethod
    def _estimate_time_to_fill_ms(
        signal: TradingSignal,
        intent: Any | None,
    ) -> int:
        reference_time = getattr(intent, "created_at", None) or getattr(
            signal,
            "created_at",
            None,
        )
        if not isinstance(reference_time, datetime):
            return 1000
        if reference_time.tzinfo is not None:
            now = datetime.now(reference_time.tzinfo)
        else:
            now = datetime.now()
        delta = max((now - reference_time).total_seconds(), 0.0)
        return max(int(delta * 1000), 1)

    @classmethod
    def _build_execution_feedback_payload(
        cls,
        signal: TradingSignal,
        intent: Any | None,
        resp: dict[str, Any],
    ) -> dict[str, Any]:
        filled_quantity = float(
            resp.get("filled_quantity")
            or signal.executed_quantity
            or signal.suggested_quantity
            or 0.0
        )
        ordered_quantity = float(
            signal.suggested_quantity
            or filled_quantity
            or getattr(intent, "qty", 0.0)
            or 0.0
        )
        arrival_price = float(
            signal.suggested_price
            or signal.executed_price
            or resp.get("avg_fill_price")
            or 0.0
        )
        fill_price = float(
            resp.get("avg_fill_price")
            or signal.executed_price
            or arrival_price
            or 0.0
        )
        reference_price = arrival_price or fill_price or 100.0
        return {
            "intent_id": int(getattr(intent, "id", 0) or 0),
            "account_id": signal.account_id,
            "symbol": signal.symbol,
            "direction": cls._resolve_execution_side(signal),
            "arrival_price": reference_price,
            "fill_price": fill_price or reference_price,
            "mid_at_order": reference_price,
            "vwap": reference_price,
            "quantity_ordered": ordered_quantity or filled_quantity,
            "quantity_filled": filled_quantity or ordered_quantity,
            "time_to_fill_ms": cls._estimate_time_to_fill_ms(signal, intent),
            "algo_type": str(resp.get("order_type") or "MARKET").upper(),
        }

    async def _record_execution_feedback(
        self,
        signal: TradingSignal,
        intent: Any | None,
        resp: dict[str, Any],
    ) -> None:
        if intent is None or getattr(intent, "id", None) is None:
            return
        from app.models.execution_quality_log import ExecutionQualityLog
        from app.services.execution_microscope_service import \
            execution_microscope_service

        existing_stmt = select(ExecutionQualityLog.id).where(
            ExecutionQualityLog.intent_id == int(intent.id)
        ).limit(1)
        existing = (
            await self.session.execute(existing_stmt)
        ).scalars().first()
        if existing is not None:
            return

        payload = self._build_execution_feedback_payload(signal, intent, resp)
        if payload["intent_id"] <= 0 or payload["quantity_filled"] <= 0:
            return

        execution_log = await (
            execution_microscope_service.record_execution_quality(
                self.session,
                **payload,
            )
        )
        from app.services.execution_policy_service import \
            execution_policy_service

        await (
            execution_policy_service
            .update_persistent_feedback_profile_from_execution(
                self.session,
                account_id=signal.account_id,
                symbol=signal.symbol,
                intent=intent,
                log=execution_log,
            )
        )
    
    async def monitor_order_status(
        self,
        account_id: str,
        order_id: str,
        status_resp: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """监控订单状态并同步到信号状态"""
        
        # 🛡️ 参数检查
        if not order_id:
            return {"status": "UNKNOWN", "message": "No order_id provided"}

        # 1. 从券商获取最新状态
        if status_resp is None:
            print(f"[OrderExecutor] Checking status for order {order_id}")
            resp = await self.broker.get_order_status(account_id, order_id)
        else:
            resp = status_resp
        status = resp.get("status")
        intent = None
        
        # 2. 更新关联的信号状态
        from app.models.execution_intent import AutonomousExecutionIntent

        # 精确匹配 order_id (string)
        stmt = select(TradingSignal).where(
            TradingSignal.order_id == str(order_id)
        )
        result = await self.session.execute(stmt)
        signal = result.scalars().first()

        if signal is None:
            intent_stmt = (
                select(AutonomousExecutionIntent)
                .where(AutonomousExecutionIntent.order_id == str(order_id))
                .order_by(
                    AutonomousExecutionIntent.updated_at.desc(),
                    AutonomousExecutionIntent.id.desc(),
                )
            )
            intent_result = await self.session.execute(intent_stmt)
            intent = intent_result.scalars().first()

            if intent is not None:
                if intent.signal_db_id is not None:
                    signal_by_dbid = await self.session.execute(
                        select(TradingSignal).where(
                            TradingSignal.id == intent.signal_db_id
                        )
                    )
                    signal = signal_by_dbid.scalars().first()

                if signal is None and intent.signal_id:
                    signal_by_sid = await self.session.execute(
                        select(TradingSignal).where(
                            TradingSignal.signal_id == str(intent.signal_id)
                        )
                    )
                    signal = signal_by_sid.scalars().first()
        else:
            intent_stmt = (
                select(AutonomousExecutionIntent)
                .where(AutonomousExecutionIntent.order_id == str(order_id))
                .order_by(
                    AutonomousExecutionIntent.updated_at.desc(),
                    AutonomousExecutionIntent.id.desc(),
                )
                .limit(1)
            )
            intent_result = await self.session.execute(intent_stmt)
            intent = intent_result.scalars().first()
        if signal:
            # 状态映射
            if status == "FILLED":
                signal.status = SignalStatus.EXECUTED
                signal.executed_price = resp.get("avg_fill_price")
                signal.executed_quantity = resp.get("filled_quantity")
                signal.executed_at = datetime.now()
            elif status == "CANCELLED":
                signal.status = SignalStatus.CANCELLED
                signal.order_id = None
            elif status == "REJECTED":
                signal.status = SignalStatus.REJECTED
                signal.order_id = None
            
            await self.session.commit()
            await self._sync_position_lifecycle_from_order_status(
                order_id=str(order_id),
                broker_status=str(status or ""),
                broker_message=resp.get("message"),
                avg_fill_price=resp.get("avg_fill_price"),
                filled_quantity=resp.get("filled_quantity"),
            )
            if status == "FILLED":
                await self._record_execution_feedback(signal, intent, resp)
            print(
                "[OrderExecutor] Updated signal "
                f"{signal.signal_id} ({signal.symbol}) status to "
                f"{signal.status.value}. Broker status: {status}"
            )

            # 3. 如果已成交或失败，更新交易日志
            try:
                from app.services.journal_service import JournalService
                journal_svc = JournalService(self.session)
                
                updates: dict = {}
                if status == "FILLED":
                    updates = {
                        "journal_status": "COMPLETED",
                        "entry_price": resp.get("avg_fill_price"),
                        "quantity": resp.get("filled_quantity")
                    }
                elif status == "CANCELLED":
                    updates = {
                        "journal_status": "FAILED",
                        "lesson_learned": (
                            "交易已撤销 (Broker CANCELLED): "
                            f"{resp.get('message') or ''}"
                        ),
                    }
                elif status == "REJECTED":
                    updates = {
                        "journal_status": "FAILED",
                        "lesson_learned": (
                            "交易被拒绝 (Broker REJECTED): "
                            f"{resp.get('message') or ''}"
                        ),
                    }
                
                if updates:
                    # 先尝试更新现有日志
                    updated = await journal_svc.update_journal_by_signal(
                        signal.signal_id,
                        updates,
                    )
                    # 如果不存在（如被风控拒绝前未记录），则创建新日志
                    if not updated and (status in ["CANCELLED", "REJECTED"]):
                        await journal_svc.create_from_execution(
                            account_id=signal.account_id,
                            symbol=signal.symbol,
                            direction=signal.direction,
                            price=signal.suggested_price or 0.0,
                            quantity=signal.suggested_quantity or 0.0,
                            signal_id=signal.signal_id
                        )
                        # 创建后再更新一次状态以填入失败理由
                        await journal_svc.update_journal_by_signal(
                            signal.signal_id,
                            updates,
                        )
            except Exception as e:
                print(
                    "[OrderExecutor] Failed to update journal for signal "
                    f"{signal.signal_id}: {e}"
                )
        else:
            logger.debug(
                "[OrderExecutor] No signal found matching order_id=%s "
                "during status sync",
                order_id,
            )
        
        return resp

    async def _sync_position_lifecycle_from_order_status(
        self,
        *,
        order_id: str,
        broker_status: str,
        broker_message: Optional[str],
        avg_fill_price: Any,
        filled_quantity: Any,
    ) -> None:
        """将券商订单状态同步到 ExecutionSlice / Position 生命周期。

        关键目的：避免订单在券商侧已 FILLED，但 Position 仍停留在 CLOSING / OPENING。
        """
        from app.models.execution_intent import AutonomousExecutionIntent
        from app.services.position_lifecycle_manager import \
            PositionLifecycleManager

        intent = (
            await self.session.execute(
                select(AutonomousExecutionIntent)
                .where(AutonomousExecutionIntent.order_id == str(order_id))
                .order_by(
                    AutonomousExecutionIntent.updated_at.desc(),
                    AutonomousExecutionIntent.id.desc(),
                )
                .limit(1)
            )
        ).scalars().first()
        if intent is None or intent.execution_slice_id is None:
            return

        slice_row = (
            await self.session.execute(
                select(ExecutionSlice).where(
                    ExecutionSlice.id == intent.execution_slice_id
                )
            )
        ).scalars().first()
        if slice_row is None:
            return

        normalized_status = str(broker_status or "").upper()
        if normalized_status == "FILLED":
            if slice_row.status == SliceStatus.FILLED.value:
                return

            resolved_qty_raw = (
                filled_quantity
                if filled_quantity not in (None, "")
                else slice_row.requested_qty
            )
            try:
                resolved_qty = float(resolved_qty_raw)
            except (TypeError, ValueError):
                resolved_qty = float(slice_row.requested_qty or 0.0)

            resolved_avg_price_raw = (
                avg_fill_price
                if avg_fill_price not in (None, "")
                else (
                    slice_row.avg_fill_price
                    if slice_row.avg_fill_price is not None
                    else 0.0
                )
            )
            try:
                resolved_avg_price = float(resolved_avg_price_raw)
            except (TypeError, ValueError):
                resolved_avg_price = float(slice_row.avg_fill_price or 0.0)

            if resolved_qty <= 0:
                resolved_qty = float(slice_row.requested_qty or 0.0)

            partial = resolved_qty < float(slice_row.requested_qty or 0.0)
            plm = PositionLifecycleManager(self.session)
            await plm.on_slice_filled(
                slice_id=slice_row.id,
                filled_qty=resolved_qty,
                avg_price=resolved_avg_price,
                partial=partial,
            )
            return

        if normalized_status in {"CANCELLED", "REJECTED"}:
            if slice_row.status in {
                SliceStatus.FAILED.value,
                SliceStatus.CANCELLED.value,
                SliceStatus.FILLED.value,
            }:
                return

            plm = PositionLifecycleManager(self.session)
            await plm.on_slice_failed(
                slice_id=slice_row.id,
                error_message=str(broker_message or normalized_status),
                actor="broker_sync",
            )
    
    async def cancel_signal(self, signal_id: str) -> bool:
        """取消信号(如果还未执行)"""
        
        stmt = select(TradingSignal).where(
            TradingSignal.signal_id == signal_id
        )
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

    async def sync_executing_orders(self, account_id: str) -> Dict[str, Any]:
        """批量同步执行中订单的状态"""
        from app.models.trading_signal import SignalStatus, TradingSignal

        # 1. 查找所有处理中的信号
        stmt = select(TradingSignal).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.status == SignalStatus.EXECUTING
            )
        )
        result = await self.session.execute(stmt)
        active_signals = result.scalars().all()
        
        if not active_signals:
            return {"synced": 0, "updates": 0}
            
        print(f"[OrderExecutor] Syncing {len(active_signals)} executing orders for account {account_id}")
        
        updates = 0
        for signal in active_signals:
            if not signal.order_id:
                continue
                
            try:
                # 获取券商侧状态
                resp = await self.monitor_order_status(account_id, signal.order_id)
                new_status = resp.get("status")
                
                # monitor_order_status 已经处理了 commit，我们这里记录更新数
                if new_status in ["FILLED", "CANCELLED", "REJECTED"]:
                    updates += 1
                    
                    # 如果状态变为 FAILED，且是真实的下单，我们需要补充日志
                    if new_status in ["CANCELLED", "REJECTED"]:
                        # 记录风险事件描述失败原因
                        await log_risk_event(
                            self.session,
                            account_id=account_id,
                            event_type="ORDER_FAILED",
                            level="WARNING",
                            message=f"Order {signal.order_id} ({signal.symbol}) failed at broker: {resp.get('message')}",
                            symbol=signal.symbol
                        )
            except Exception as e:
                print(f"[OrderExecutor] Error syncing signal {signal.signal_id}: {e}")
                
        return {"synced": len(active_signals), "updates": updates}
