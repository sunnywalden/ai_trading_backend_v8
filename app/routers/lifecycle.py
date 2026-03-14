"""V10.3: 交易生命周期 API Router

端点：
  GET /api/v1/lifecycle/pipeline            — 17 阶段 Pipeline 任务分布
  GET /api/v1/lifecycle/plan-fsm            — Plan FSM 状态计数
  GET /api/v1/lifecycle/position-fsm        — Position FSM 状态计数 + 引擎统计
  GET /api/v1/lifecycle/position-board      — 持仓看板（按 Position FSM 分组）
  GET /api/v1/lifecycle/fsm-events          — FSM 转换事件流（分页）
  GET /api/v1/lifecycle/provenance/{id}     — 单笔决策溯源链
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.schemas.lifecycle import (
    DecisionProvenance,
    FsmEventPage,
    LifecycleCoherenceSummary,
    PipelineDistribution,
    PlanFsmSummary,
    PositionBoard,
    PositionFsmSummary,
)
from app.services.lifecycle_coherence_service import lifecycle_coherence_service
from app.services.lifecycle_service import lifecycle_service

router = APIRouter(prefix="/api/v1/lifecycle", tags=["V10.3 交易生命周期"])


@router.get(
    "/pipeline", response_model=PipelineDistribution, summary="17阶段Pipeline分布"
)
async def get_pipeline_distribution(
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """返回当前各 Pipeline 阶段的任务卡片分布，用于渲染 Kanban 看板。"""
    return await lifecycle_service.get_pipeline_distribution(db)


@router.get("/plan-fsm", response_model=PlanFsmSummary, summary="Plan FSM状态统计")
async def get_plan_fsm(
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """返回 Plan FSM 各状态的计划数量，用于渲染状态气泡图。"""
    return await lifecycle_service.get_plan_fsm_counts(db)


@router.get(
    "/position-fsm",
    response_model=PositionFsmSummary,
    summary="Position FSM状态统计",
)
async def get_position_fsm(
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """返回 Position FSM 各状态数量及 ScaleIn/Out/Trailing 引擎触发统计。"""
    return await lifecycle_service.get_position_fsm_counts(db)


@router.get("/position-board", response_model=PositionBoard, summary="持仓看板")
async def get_position_board(
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """返回按 Position FSM 状态分组的持仓看板，用于持仓生命周期页面。"""
    return await lifecycle_service.get_position_board(db)


@router.get("/fsm-events", response_model=FsmEventPage, summary="FSM转换事件流")
async def get_fsm_events(
    db: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    size: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
    fsm_type: Annotated[
        Optional[str],
        Query(description="过滤类型：PLAN / POSITION"),
    ] = None,
):
    """返回 FSM 状态转换事件流，支持按 PLAN / POSITION 过滤，降序排列。"""
    return await lifecycle_service.get_fsm_events(
        db, page=page, size=size, fsm_type=fsm_type
    )


@router.get(
    "/provenance/{plan_id}",
    response_model=DecisionProvenance,
    summary="单笔决策溯源链",
    responses={404: {"description": "Trading plan not found"}},
)
async def get_provenance(
    plan_id: int,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """返回单笔交易的 5 卡片决策溯源链：六维信号 / 风险门控 / AI推理 / 执行进度 / 持仓状态。"""
    result = await lifecycle_service.get_provenance(db, plan_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"TradingPlan {plan_id} not found",
        )
    return result


@router.post(
    "/coherence/reconcile",
    response_model=LifecycleCoherenceSummary,
    summary="双视角一致性自动纠偏",
    responses={503: {"description": "Runtime account id unavailable"}},
)
async def reconcile_lifecycle_coherence(
    db: Annotated[AsyncSession, Depends(get_session)],
    auto_heal: Annotated[bool, Query(description="是否执行自动纠偏")] = True,
):
    account_id = await lifecycle_coherence_service.resolve_account_id()
    if not account_id:
        raise HTTPException(
            status_code=503,
            detail="Unable to resolve runtime account id",
        )
    return await lifecycle_coherence_service.inspect_and_reconcile(
        db,
        account_id=account_id,
        auto_heal=auto_heal,
    )
