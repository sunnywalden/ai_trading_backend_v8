from __future__ import annotations

from typing import Optional, Dict, Iterable
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_plan import TradingPlan


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
