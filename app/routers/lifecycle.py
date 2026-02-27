"""V10.3: 交易生命周期 API Router

端点：
  GET /api/v1/lifecycle/pipeline            — 17 阶段 Pipeline 任务分布
  GET /api/v1/lifecycle/plan-fsm            — Plan FSM 状态计数
  GET /api/v1/lifecycle/position-fsm        — Position FSM 状态计数 + 引擎统计
  GET /api/v1/lifecycle/fsm-events          — FSM 转换事件流（分页）
  GET /api/v1/lifecycle/provenance/{id}     — 单笔决策溯源链
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.services.lifecycle_service import lifecycle_service
from app.schemas.lifecycle import (
    PipelineDistribution,
    PlanFsmSummary,
    PositionFsmSummary,
    FsmEventPage,
    DecisionProvenance,
)

router = APIRouter(prefix="/api/v1/lifecycle", tags=["V10.3 交易生命周期"])


@router.get("/pipeline", response_model=PipelineDistribution, summary="17阶段Pipeline分布")
async def get_pipeline_distribution(
    db: AsyncSession = Depends(get_session),
):
    """返回当前各 Pipeline 阶段的任务卡片分布，用于渲染 Kanban 看板。"""
    return await lifecycle_service.get_pipeline_distribution(db)


@router.get("/plan-fsm", response_model=PlanFsmSummary, summary="Plan FSM状态统计")
async def get_plan_fsm(
    db: AsyncSession = Depends(get_session),
):
    """返回 Plan FSM 各状态的计划数量，用于渲染状态气泡图。"""
    return await lifecycle_service.get_plan_fsm_counts(db)


@router.get("/position-fsm", response_model=PositionFsmSummary, summary="Position FSM状态统计")
async def get_position_fsm(
    db: AsyncSession = Depends(get_session),
):
    """返回 Position FSM 各状态数量及 ScaleIn/Out/Trailing 引擎触发统计。"""
    return await lifecycle_service.get_position_fsm_counts(db)


@router.get("/fsm-events", response_model=FsmEventPage, summary="FSM转换事件流")
async def get_fsm_events(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    fsm_type: Optional[str] = Query(None, description="过滤类型：PLAN / POSITION"),
    db: AsyncSession = Depends(get_session),
):
    """返回 FSM 状态转换事件流，支持按 PLAN / POSITION 过滤，降序排列。"""
    return await lifecycle_service.get_fsm_events(db, page=page, size=size, fsm_type=fsm_type)


@router.get("/provenance/{plan_id}", response_model=DecisionProvenance, summary="单笔决策溯源链")
async def get_provenance(
    plan_id: int,
    db: AsyncSession = Depends(get_session),
):
    """返回单笔交易的 5 卡片决策溯源链：六维信号 / 风险门控 / AI推理 / 执行进度 / 持仓状态。"""
    result = await lifecycle_service.get_provenance(db, plan_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"TradingPlan {plan_id} not found")
    return result
