from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from sqlalchemy import select, desc, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import (
    Strategy,
    StrategyRun,
    HistoricalStrategyRun,
    StrategyRunAsset,
    StrategyRunLog,
    StrategyNotification,
)


class StrategyService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_strategies(
        self,
        style: Optional[str] = None,
        is_builtin: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> List[Strategy]:
        stmt = select(Strategy)
        if style is not None:
            stmt = stmt.where(Strategy.style == style)
        if is_builtin is not None:
            stmt = stmt.where(Strategy.is_builtin == is_builtin)
        if search:
            stmt = stmt.where(Strategy.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(desc(Strategy.created_at)).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_strategy(self, strategy_id: str) -> Optional[Strategy]:
        stmt = select(Strategy).where(Strategy.id == strategy_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def create_strategy(self, payload: Dict[str, Any], owner_id: str) -> Strategy:
        strategy = Strategy(id=str(uuid4()), owner_id=owner_id, **payload)
        self.session.add(strategy)
        await self.session.commit()
        await self.session.refresh(strategy)
        return strategy

    async def update_strategy_params(self, strategy_id: str, params: Dict[str, Any]) -> Optional[Strategy]:
        strategy = await self.get_strategy(strategy_id)
        if not strategy:
            return None
        strategy.default_params = params
        strategy.version = (strategy.version or 1) + 1
        strategy.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(strategy)
        return strategy
    
    async def toggle_strategy(self, strategy_id: str, is_active: bool) -> Optional[Strategy]:
        """启用/禁用策略"""
        strategy = await self.get_strategy(strategy_id)
        if not strategy:
            return None
        strategy.is_active = is_active
        strategy.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(strategy)
        return strategy


class StrategyRunService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(
        self,
        strategy: Strategy,
        user_id: str,
        account_id: str,
        direction: Optional[str],
        notify_channels: Optional[Iterable[str]] = None,
        target_universe: Optional[str] = None,
        min_score: Optional[int] = None,
        max_results: Optional[int] = None,
        priority: Optional[int] = None,
    ) -> StrategyRun:
        run = StrategyRun(
            id=str(uuid4()),
            strategy_id=strategy.id,
            strategy_version=strategy.version,
            user_id=user_id,
            account_id=account_id,
            direction=direction,
            notify_channels=list(notify_channels or []),
            target_universe=target_universe,
            min_score=min_score,
            max_results=max_results,
            priority=priority,
            status="QUEUED",
        )

        self.session.add(run)
        if strategy:
            strategy.last_run_status = run.status
            strategy.last_run_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get_run_by_id(self, run_id: str) -> Optional[StrategyRun]:
        stmt = select(StrategyRun).where(StrategyRun.id == run_id).options(
            selectinload(StrategyRun.strategy),
            selectinload(StrategyRun.history)
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def assign_task_id(self, run_id: str, task_id: str) -> None:
        run = await self.get_run_by_id(run_id)
        if not run:
            return
        run.celery_task_id = task_id
        await self.session.commit()
        await self.session.refresh(run)

    async def list_runs(
        self,
        limit: int = 20,
        offset: int = 0,
        strategy_id: Optional[str] = None,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[StrategyRun]:
        stmt = select(StrategyRun).options(selectinload(StrategyRun.history))
        filters = []
        if strategy_id:
            filters.append(StrategyRun.strategy_id == strategy_id)
        if account_id:
            filters.append(StrategyRun.account_id == account_id)
        if status:
            filters.append(StrategyRun.status == status)
        if filters:
            stmt = stmt.where(and_(*filters))
        stmt = stmt.order_by(desc(StrategyRun.created_at)).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_latest_run(self, account_id: Optional[str] = None, strategy_id: Optional[str] = None) -> Optional[StrategyRun]:
        stmt = select(StrategyRun).options(selectinload(StrategyRun.history))
        if account_id:
            stmt = stmt.where(StrategyRun.account_id == account_id)
        if strategy_id:
            stmt = stmt.where(StrategyRun.strategy_id == strategy_id)
        stmt = stmt.order_by(desc(StrategyRun.created_at)).limit(1)
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_historical_result(self, run_id: str) -> Optional[HistoricalStrategyRun]:
        stmt = select(HistoricalStrategyRun).where(HistoricalStrategyRun.strategy_run_id == run_id)
        res = await self.session.execute(stmt)
        return res.scalars().first()
