from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.db import get_session
from app.schemas.trading_plan import PlanCreateRequest, PlanUpdateRequest, PlanListResponse, PlanView
from app.services.trading_plan_service import TradingPlanService
from app.core.config import settings

router = APIRouter()


@router.get("/plan/list", response_model=PlanListResponse)
async def list_plans(
    status: Optional[str] = Query(None, description="筛选计划状态"),
    symbol: Optional[str] = Query(None, description="筛选标的"),
    session: AsyncSession = Depends(get_session),
):
    account_id = settings.TIGER_ACCOUNT
    svc = TradingPlanService(session)
    plans = await svc.list_plans(account_id=account_id, status=status, symbol=symbol)
    views = [PlanView.model_validate(p) for p in plans]
    return PlanListResponse(total=len(views), plans=views)


@router.post("/plan/create", response_model=PlanView)
async def create_plan(
    payload: PlanCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    account_id = settings.TIGER_ACCOUNT
    svc = TradingPlanService(session)
    try:
        plan = await svc.create_plan(account_id, payload.model_dump())
        return PlanView.model_validate(plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/plan/{plan_id}", response_model=PlanView)
async def update_plan(
    plan_id: int,
    payload: PlanUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = TradingPlanService(session)
    plan = await svc.update_plan(plan_id, payload.model_dump(exclude_none=True))
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PlanView.model_validate(plan)


@router.delete("/plan/{plan_id}")
async def delete_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
):
    svc = TradingPlanService(session)
    ok = await svc.delete_plan(plan_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"status": "ok", "deleted": True}
