from __future__ import annotations

from typing import Optional, Dict, Iterable, List, Any
from datetime import datetime
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_plan import TradingPlan
from app.models.trading_signal import TradingSignal, SignalType, SignalStatus, SignalSource
from app.engine.order_executor import OrderExecutor
from app.core.config import settings
import uuid


class TradingPlanService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_plans(
        self,
        account_id: str,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> list[TradingPlan]:
        stmt = select(TradingPlan).where(TradingPlan.account_id == account_id)
        if status:
            stmt = stmt.where(TradingPlan.plan_status == status)
        if symbol:
            stmt = stmt.where(TradingPlan.symbol == symbol)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_active_plans_by_symbols(
        self,
        account_id: str,
        symbols: Iterable[str],
    ) -> Dict[str, TradingPlan]:
        symbol_list = list(set(symbols))
        if not symbol_list:
            return {}
        stmt = select(TradingPlan).where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.plan_status == "ACTIVE",
                TradingPlan.symbol.in_(symbol_list),
            )
        )
        res = await self.session.execute(stmt)
        plans = res.scalars().all()
        return {p.symbol: p for p in plans}

    async def create_plan(self, account_id: str, payload: dict) -> TradingPlan:
        self._validate_payload(payload)
        plan = TradingPlan(account_id=account_id, **payload)
        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)
        return plan

    async def update_plan(self, plan_id: int, payload: dict) -> Optional[TradingPlan]:
        stmt = select(TradingPlan).where(TradingPlan.id == plan_id)
        res = await self.session.execute(stmt)
        plan = res.scalars().first()
        if not plan:
            return None

        for k, v in payload.items():
            setattr(plan, k, v)

        await self.session.commit()
        await self.session.refresh(plan)
        return plan

    async def delete_plan(self, plan_id: int) -> bool:
        stmt = select(TradingPlan).where(TradingPlan.id == plan_id)
        res = await self.session.execute(stmt)
        plan = res.scalars().first()
        if not plan:
            return False
        await self.session.delete(plan)
        await self.session.commit()
        return True

    def _validate_payload(self, payload: dict) -> None:
        entry_price = payload.get("entry_price")
        stop_loss = payload.get("stop_loss")
        take_profit = payload.get("take_profit")
        target_position = payload.get("target_position")

        if entry_price is None or entry_price <= 0:
            raise ValueError("entry_price must be > 0")
        if stop_loss is None or stop_loss <= 0:
            raise ValueError("stop_loss must be > 0")
        if take_profit is None or take_profit <= 0:
            raise ValueError("take_profit must be > 0")
        if not (stop_loss < entry_price):
            raise ValueError("stop_loss must be < entry_price")
        if not (take_profit > entry_price):
            raise ValueError("take_profit must be > entry_price")
        if target_position is None or target_position <= 0 or target_position > 1:
            raise ValueError("target_position must be in (0, 1]")

    async def get_plan_by_id(self, plan_id: int) -> Optional[TradingPlan]:
        """根据ID获取交易计划"""
        stmt = select(TradingPlan).where(TradingPlan.id == plan_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_plans_with_pagination(
        self,
        account_id: str,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        page: int = 1,
        page_size: int = 50
    ) -> tuple[List[TradingPlan], int]:
        """分页获取交易计划列表"""
        # 构建查询条件
        conditions = [TradingPlan.account_id == account_id]
        if status:
            conditions.append(TradingPlan.plan_status == status)
        if symbol:
            conditions.append(TradingPlan.symbol == symbol)
        
        # 查询总数
        count_stmt = select(func.count()).select_from(TradingPlan).where(and_(*conditions))
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar()
        
        # 查询分页数据
        stmt = (
            select(TradingPlan)
            .where(and_(*conditions))
            .order_by(TradingPlan.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        res = await self.session.execute(stmt)
        plans = list(res.scalars().all())
        
        return plans, total

    async def execute_plan(self, plan_id: int) -> Dict[str, Any]:
        """执行单个交易计划"""
        # 获取计划
        plan = await self.get_plan_by_id(plan_id)
        if not plan:
            raise ValueError(f"交易计划 {plan_id} 不存在")
        
        if plan.plan_status != "ACTIVE":
            raise ValueError(f"计划状态为 {plan.plan_status}，不能执行")
        
        # 创建交易信号
        signal = await self._create_signal_from_plan(plan)
        
        # 执行信号
        executor = OrderExecutor(self.session)
        result = await self._execute_signal(executor, signal)
        
        # 更新计划状态
        if result.get("success"):
            plan.plan_status = "EXECUTED"
        else:
            plan.plan_status = "FAILED"
        
        plan.notes = f"{plan.notes or ''} | Executed at {datetime.utcnow()}"
        await self.session.commit()
        
        return {
            "plan_id": plan_id,
            "signal_id": signal.signal_id,
            "success": result.get("success"),
            "order_id": result.get("order_id"),
            "message": result.get("message"),
            "error": result.get("error")
        }

    async def batch_execute_plans(self, plan_ids: List[int]) -> Dict[str, Any]:
        """批量执行交易计划"""
        results = {
            "total": len(plan_ids),
            "success_count": 0,
            "failed_count": 0,
            "details": []
        }
        
        for plan_id in plan_ids:
            try:
                result = await self.execute_plan(plan_id)
                if result["success"]:
                    results["success_count"] += 1
                else:
                    results["failed_count"] += 1
                results["details"].append(result)
            except Exception as e:
                results["failed_count"] += 1
                results["details"].append({
                    "plan_id": plan_id,
                    "success": False,
                    "error": str(e)
                })
        
        return results

    async def cancel_plan(self, plan_id: int, reason: Optional[str] = None) -> bool:
        """取消交易计划"""
        plan = await self.get_plan_by_id(plan_id)
        if not plan:
            return False
        
        plan.plan_status = "CANCELLED"
        if reason:
            plan.notes = f"{plan.notes or ''} | Cancelled: {reason}"
        await self.session.commit()
        return True

    async def batch_cancel_plans(self, plan_ids: List[int], reason: Optional[str] = None) -> int:
        """批量取消交易计划"""
        cancelled_count = 0
        for plan_id in plan_ids:
            if await self.cancel_plan(plan_id, reason):
                cancelled_count += 1
        return cancelled_count

    async def _create_signal_from_plan(self, plan: TradingPlan) -> TradingSignal:
        """从交易计划创建信号"""
        signal = TradingSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.ENTRY,
            signal_source=SignalSource.MANUAL,
            status=SignalStatus.GENERATED,
            symbol=plan.symbol,
            direction="LONG",  # 从 entry_price 推断
            signal_strength=70,
            confidence=0.7,
            expected_return=0.1,
            risk_score=50,
            suggested_quantity=int(plan.target_position * 100),  # 简化计算
            suggested_price=float(plan.entry_price),
            stop_loss=float(plan.stop_loss),
            take_profit=float(plan.take_profit),
            max_holding_days=30,
            account_id=plan.account_id,
            user_id="system",
            risk_check_passed="PENDING",
            notes=f"From Trading Plan #{plan.id}",
            generated_at=datetime.utcnow()
        )
        
        self.session.add(signal)
        await self.session.commit()
        await self.session.refresh(signal)
        return signal

    async def _execute_signal(self, executor: OrderExecutor, signal: TradingSignal) -> Dict[str, Any]:
        """执行交易信号"""
        try:
            # 获取账户权益
            from app.broker.factory import make_option_broker_client
            broker = make_option_broker_client()
            account_equity = await broker.get_account_equity(signal.account_id)
            
            if not account_equity or account_equity <= 0:
                account_equity = 1000000.0  # 默认值
            
            # 标记信号为已验证
            signal.status = SignalStatus.VALIDATED
            signal.risk_check_passed = "YES"
            await self.session.commit()
            
            # 执行信号
            from app.core.trade_mode import TradeMode
            trade_mode = TradeMode[settings.TRADE_MODE.upper()] if hasattr(settings, 'TRADE_MODE') else TradeMode.REAL
            
            result = await executor._execute_single_signal(
                signal=signal,
                account_equity=account_equity,
                trade_mode=trade_mode
            )
            
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"执行失败: {e}"
            }
