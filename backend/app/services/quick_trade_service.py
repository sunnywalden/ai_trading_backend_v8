"""快捷交易服务 - 从策略结果到订单执行的桥梁"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import StrategyRun, StrategyRunAsset
from app.models.trading_signal import TradingSignal, SignalType, SignalStatus, SignalSource
from app.providers.market_data_provider import MarketDataProvider
from app.broker.factory import make_option_broker_client
from app.engine.order_executor import OrderExecutor
from app.core.config import settings


class QuickTradeService:
    """快捷交易服务 - 将策略运行结果快速转换为可执行的交易信号"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.market_data = MarketDataProvider()
        self.broker = make_option_broker_client()
        self.executor = OrderExecutor(self.session)
    
    async def preview_quick_trade(
        self,
        run_id: str,
        symbol: str,
        risk_budget: Optional[float] = None
    ) -> Dict[str, Any]:
        """预览快捷交易参数（不创建信号，仅计算）"""
        
        # 1. 获取策略运行资产数据
        asset = await self._get_strategy_asset(run_id, symbol)
        if not asset:
            raise ValueError(f"未找到策略运行 {run_id} 中的标的 {symbol}")
        
        # 2. 尝试获取当前市场价格（确保准确性）
        print(f"[QuickTradeService] 获取 {symbol} 当前价格...")
        try:
            current_price = await self._get_current_price(symbol)
            print(f"[QuickTradeService] {symbol} 当前价格: ${current_price:.2f}")
            price_available = True
        except Exception as e:
            print(f"[QuickTradeService] 无法获取 {symbol} 价格，将使用市价单模式: {e}")
            current_price = None
            price_available = False
        
        # 3. 获取账户权益
        account_equity = await self._get_account_equity()
        
        # 4. 根据价格可用性选择模式
        if price_available:
            # 模式A: 限价单模式（有准确价格）
            quantity = await self._calculate_quantity(
                symbol=symbol,
                suggested_weight=asset.weight or 0.2,
                account_equity=account_equity,
                current_price=current_price,
                risk_budget=risk_budget
            )
            
            stop_loss, take_profit = self._calculate_risk_levels(
                current_price=current_price,
                direction=asset.direction,
                signal_strength=asset.signal_strength or 70
            )
            
            position_value = quantity * current_price
            position_ratio = position_value / account_equity if account_equity > 0 else 0
            risk_score = self._assess_risk(asset, position_ratio)
            
            return {
                "symbol": symbol,
                "order_mode": "LIMIT",
                "price_available": True,
                "current_price": current_price,
                "suggested_direction": asset.direction or "LONG",
                "suggested_action": asset.action or "BUY",
                "signal_strength": asset.signal_strength or 0,
                "suggested_weight": asset.weight or 0,
                "calculated_quantity": quantity,
                "calculated_stop_loss": stop_loss,
                "calculated_take_profit": take_profit,
                "estimated_position_value": position_value,
                "estimated_position_ratio": position_ratio,
                "risk_score": risk_score,
                "risk_flags": asset.risk_flags or [],
                "signal_dimensions": asset.signal_dimensions or {}
            }
        else:
            # 模式B: 市价单模式（无准确价格）
            return {
                "symbol": symbol,
                "order_mode": "MARKET",
                "price_available": False,
                "current_price": None,
                "suggested_direction": asset.direction or "LONG",
                "suggested_action": asset.action or "BUY",
                "signal_strength": asset.signal_strength or 0,
                "suggested_weight": asset.weight or 0,
                "calculated_quantity": None,  # 市价单不预估数量
                "calculated_stop_loss": None,  # 不设置止损
                "calculated_take_profit": None,  # 不设置止盈
                "estimated_position_value": None,
                "estimated_position_ratio": None,
                "risk_score": 50,  # 中等风险
                "risk_flags": asset.risk_flags or [],
                "signal_dimensions": asset.signal_dimensions or {},
                "warning": "无法获取实时价格，将以市价单执行，不设置止盈止损"
            }
    
    async def execute_quick_trade(
        self,
        run_id: str,
        symbol: str,
        execution_mode: str = "IMMEDIATE",
        override_params: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行快捷交易"""
        
        # 1. 获取预览数据
        preview = await self.preview_quick_trade(run_id, symbol, override_params.get("risk_budget") if override_params else None)
        
        # 2. 应用用户覆盖参数（仅在限价单模式下生效）
        if override_params and preview.get("price_available"):
            if override_params.get("override_direction"):
                preview["suggested_direction"] = override_params["override_direction"]
            if override_params.get("override_quantity"):
                preview["calculated_quantity"] = override_params["override_quantity"]
            if override_params.get("override_price"):
                preview["current_price"] = override_params["override_price"]
            if override_params.get("override_stop_loss"):
                preview["calculated_stop_loss"] = override_params["override_stop_loss"]
            if override_params.get("override_take_profit"):
                preview["calculated_take_profit"] = override_params["override_take_profit"]
        
        # 3. 创建交易信号
        order_mode = preview.get("order_mode", "LIMIT")
        signal_notes = notes or f"策略快捷交易: {symbol} [{order_mode}]"
        
        signal = await self._create_signal_from_preview(
            run_id=run_id,
            preview=preview,
            notes=signal_notes
        )
        
        # 4. 根据执行模式处理
        if execution_mode == "IMMEDIATE":
            # 立即执行
            result = await self._execute_signal_immediately(signal)
            return {
                "status": "executed",
                "signal_id": signal.signal_id,
                "order_id": result.get("order_id"),
                "message": f"交易信号已执行，订单ID: {result.get('order_id')}",
                "preview": preview
            }
        elif execution_mode == "PLAN":
            # 创建交易计划
            plan_id = await self._create_trading_plan(signal, preview)
            return {
                "status": "plan_created",
                "signal_id": signal.signal_id,
                "plan_id": plan_id,
                "message": f"交易计划已创建，计划ID: {plan_id}",
                "preview": preview
            }
        else:
            # 仅创建信号，等待后续执行
            return {
                "status": "signal_created",
                "signal_id": signal.signal_id,
                "message": "交易信号已创建，等待执行",
                "preview": preview
            }
    
    async def batch_quick_trade(
        self,
        run_id: str,
        symbols: List[str],
        execution_mode: str = "IMMEDIATE",
        position_sizing_method: str = "WEIGHT",
        custom_weights: Optional[Dict[str, float]] = None,
        total_risk_budget: float = 0.3,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """批量快捷交易"""
        
        results = {
            "total_signals": len(symbols),
            "success_count": 0,
            "failed_count": 0,
            "signal_ids": [],
            "failures": []
        }
        
        # 重新计算权重
        weights = await self._calculate_batch_weights(
            run_id, symbols, position_sizing_method, custom_weights, total_risk_budget
        )
        
        for symbol in symbols:
            try:
                risk_budget = weights.get(symbol, total_risk_budget / len(symbols))
                result = await self.execute_quick_trade(
                    run_id=run_id,
                    symbol=symbol,
                    execution_mode=execution_mode,
                    override_params={"risk_budget": risk_budget},
                    notes=notes
                )
                results["signal_ids"].append(result["signal_id"])
                results["success_count"] += 1
            except Exception as e:
                results["failed_count"] += 1
                results["failures"].append({
                    "symbol": symbol,
                    "error": str(e)
                })
        
        return results
    
    # ==================== 私有辅助方法 ====================
    
    async def _get_strategy_asset(self, run_id: str, symbol: str) -> Optional[StrategyRunAsset]:
        """获取策略运行资产"""
        stmt = select(StrategyRunAsset).where(
            StrategyRunAsset.strategy_run_id == run_id,
            StrategyRunAsset.symbol == symbol
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def _get_current_price(self, symbol: str) -> float:
        """获取当前市价 - 必须返回准确价格，否则抛出异常"""
        price = await self.market_data.get_current_price(symbol)
        
        if not price or price <= 0:
            raise ValueError(f"无法获取 {symbol} 的准确价格，当前返回值: {price}")
        
        return price
    
    async def _get_account_equity(self) -> float:
        """获取账户权益 - 必须返回准确值，否则抛出异常"""
        try:
            account_id = settings.TIGER_ACCOUNT
            equity = await self.broker.get_account_equity(account_id)
            
            if not equity or equity <= 0:
                raise ValueError(f"账户 {account_id} 权益数据异常: {equity}")
            
            return equity
        except Exception as e:
            print(f"[QuickTradeService] 无法获取账户权益: {e}")
            raise ValueError(f"无法获取账户 {settings.TIGER_ACCOUNT} 的准确权益数据: {e}")
    
    async def _calculate_quantity(
        self,
        symbol: str,
        suggested_weight: float,
        account_equity: float,
        current_price: float,
        risk_budget: Optional[float] = None
    ) -> int:
        """计算交易数量"""
        budget = risk_budget if risk_budget else suggested_weight
        target_value = account_equity * budget
        quantity = int(target_value / current_price)
        return max(1, quantity)  # 至少1股
    
    def _calculate_risk_levels(
        self,
        current_price: float,
        direction: str,
        signal_strength: float
    ) -> tuple[Optional[float], Optional[float]]:
        """计算止损止盈价位"""
        # 根据信号强度调整止损止盈幅度
        stop_loss_pct = 0.05 if signal_strength >= 80 else 0.03
        take_profit_pct = 0.15 if signal_strength >= 80 else 0.10
        
        if direction == "LONG":
            stop_loss = round(current_price * (1 - stop_loss_pct), 2)
            take_profit = round(current_price * (1 + take_profit_pct), 2)
        else:
            stop_loss = round(current_price * (1 + stop_loss_pct), 2)
            take_profit = round(current_price * (1 - take_profit_pct), 2)
        
        return stop_loss, take_profit
    
    def _assess_risk(self, asset: StrategyRunAsset, position_ratio: float) -> float:
        """评估风险评分（0-100）"""
        base_risk = 50
        
        # 信号强度越高，风险越低
        if asset.signal_strength:
            base_risk -= (asset.signal_strength - 50) * 0.3
        
        # 持仓比例越高，风险越高
        if position_ratio > 0.3:
            base_risk += 20
        elif position_ratio > 0.2:
            base_risk += 10
        
        # 风险标记
        if asset.risk_flags and len(asset.risk_flags) > 0:
            base_risk += len(asset.risk_flags) * 10
        
        return max(0, min(100, base_risk))
    
    async def _create_signal_from_preview(
        self,
        run_id: str,
        preview: Dict[str, Any],
        notes: str
    ) -> TradingSignal:
        """从预览数据创建交易信号
        
        支持两种模式：
        - 限价单模式：有准确价格、数量、止盈止损
        - 市价单模式：无价格，以市价成交，不设置止盈止损
        """
        # 处理市价单模式：字段可能为 None
        order_mode = preview.get("order_mode", "LIMIT")
        
        signal = TradingSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.ENTRY,
            signal_source=SignalSource.STRATEGY,
            status=SignalStatus.GENERATED,
            symbol=preview["symbol"],
            direction=preview["suggested_direction"],
            signal_strength=preview["signal_strength"],
            confidence=preview["signal_strength"] / 100,
            expected_return=0.1,  # 默认预期收益
            risk_score=preview.get("risk_score", 50),
            suggested_quantity=preview.get("calculated_quantity"),  # 市价单为 None
            suggested_price=preview.get("current_price"),  # 市价单为 None
            stop_loss=preview.get("calculated_stop_loss"),  # 市价单为 None
            take_profit=preview.get("calculated_take_profit"),  # 市价单为 None
            max_holding_days=30,
            strategy_run_id=run_id,
            account_id=settings.TIGER_ACCOUNT,
            user_id="system",
            risk_check_passed="PENDING",
            factor_scores=preview.get("signal_dimensions", {}),
            notes=f"{notes} | Order Mode: {order_mode}",
            generated_at=datetime.utcnow()
        )
        
        self.session.add(signal)
        await self.session.commit()
        await self.session.refresh(signal)
        return signal
    
    async def _execute_signal_immediately(self, signal: TradingSignal) -> Dict[str, Any]:
        """立即执行信号"""
        try:
            # 获取账户权益
            account_equity = await self._get_account_equity()
            
            # 标记信号为已验证状态（OrderExecutor 需要）
            signal.status = SignalStatus.VALIDATED
            signal.risk_check_passed = "YES"
            await self.session.commit()
            
            # 调用 OrderExecutor 的私有方法执行单个信号
            from app.core.trade_mode import TradeMode
            trade_mode = TradeMode[settings.TRADE_MODE.upper()] if hasattr(settings, 'TRADE_MODE') else TradeMode.REAL
            
            result = await self.executor._execute_single_signal(
                signal=signal,
                account_equity=account_equity,
                trade_mode=trade_mode
            )
            
            if not result.get("success"):
                signal.status = SignalStatus.FAILED
                signal.notes = f"{signal.notes}; 执行失败: {result.get('error', 'Unknown error')}"
                await self.session.commit()
            
            return result
        except Exception as e:
            signal.status = SignalStatus.FAILED
            signal.notes = f"{signal.notes}; 执行失败: {str(e)}"
            await self.session.commit()
            raise
    
    async def _create_trading_plan(self, signal: TradingSignal, preview: Dict[str, Any]) -> int:
        """创建交易计划"""
        from app.services.trading_plan_service import TradingPlanService
        
        plan_service = TradingPlanService(self.session)
        plan = await plan_service.create_plan(
            account_id=signal.account_id,
            payload={
                "symbol": signal.symbol,
                "entry_price": signal.suggested_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "target_position": signal.suggested_quantity,
                "notes": f"快捷交易创建 (Signal: {signal.signal_id})",
                "plan_tags": {"signal_id": signal.signal_id}
            }
        )
        return plan.id
    
    async def _calculate_batch_weights(
        self,
        run_id: str,
        symbols: List[str],
        method: str,
        custom_weights: Optional[Dict[str, float]],
        total_budget: float
    ) -> Dict[str, float]:
        """计算批量交易的权重分配"""
        
        if method == "CUSTOM" and custom_weights:
            return custom_weights
        
        if method == "EQUAL":
            per_symbol = total_budget / len(symbols)
            return {symbol: per_symbol for symbol in symbols}
        
        # WEIGHT: 使用策略建议的权重
        assets = {}
        for symbol in symbols:
            asset = await self._get_strategy_asset(run_id, symbol)
            if asset:
                assets[symbol] = asset.weight or 1.0
        
        # 归一化权重
        total_weight = sum(assets.values())
        if total_weight > 0:
            return {sym: (w / total_weight) * total_budget for sym, w in assets.items()}
        
        # fallback to equal
        per_symbol = total_budget / len(symbols)
        return {symbol: per_symbol for symbol in symbols}
