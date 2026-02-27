"""V10.2-M6: AI 洞察 + A/B 实验 API 路由

Endpoints:
  GET  /api/v1/insights/repository          → 分页查询经验库
  POST /api/v1/insights/repository          → 人工新增洞察
  PATCH /api/v1/insights/repository/{id}    → 启用/禁用洞察
  GET  /api/v1/insights/experiments         → 查询 A/B 实验列表
  POST /api/v1/insights/experiments         → 创建 A/B 实验
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.schemas.insights import (
    AIInsightItemResponse,
    ABExperimentItemResponse,
    CreateExperimentRequest,
    ExperimentsListResponse,
    InsightListResponse,
    ToggleInsightRequest,
)
import logging

from app.services.insight_service import ab_test_engine, insight_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/insights", tags=["Insights"])


# ── 经验库 ────────────────────────────────────────────────────────────────────

@router.get("/repository", response_model=InsightListResponse, summary="查询 AI 经验库")
async def list_insights(
    insight_type: str | None = Query(default=None),
    regime:       str | None = Query(default=None),
    active_only:  bool = Query(default=True),
    page:         int = Query(default=1, ge=1),
    page_size:    int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    """分页查询 AI 经验库中的洞察规则。支持按类型和市场状态过滤。"""
    offset = (page - 1) * page_size
    rows, total = await insight_service.list_insights(
        db,
        insight_type=insight_type,
        regime=regime,
        active_only=active_only,
        limit=page_size,
        offset=offset,
    )
    items = [AIInsightItemResponse.model_validate(r) for r in rows]
    return InsightListResponse(items=items, total=total, page=page)


@router.post("/repository", response_model=AIInsightItemResponse, summary="人工新增洞察", status_code=201)
async def create_insight(body: dict, db: AsyncSession = Depends(get_session)):
    """手动向经验库写入一条洞察规则（运营/研究员使用）。"""
    insight = await insight_service.create_insight(db, body)
    return AIInsightItemResponse.model_validate(insight)


@router.patch("/repository/{insight_id}", summary="启用/禁用洞察")
async def toggle_insight(
    insight_id: int,
    body: ToggleInsightRequest,
    db: AsyncSession = Depends(get_session),
):
    """切换指定洞察的激活状态（active=true 表示在决策流中启用）。"""
    ok = await insight_service.toggle_active(db, insight_id, body.active)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Insight {insight_id} not found")
    return {"success": True, "active": body.active}


@router.post("/generate_weekly", response_model=InsightListResponse, summary="触发生成每周洞察")
async def trigger_generate_weekly(db: AsyncSession = Depends(get_session)):
    """手动触发每周洞察分析。该任务会读取最近 30 天交易数据并调用 Reasoner 模型生成新的 AI 洞察。"""
    from app.services.insight_service import weekly_insight_generator

    # 执行生成
    try:
        new_insights = await weekly_insight_generator.run(db)
        items = [AIInsightItemResponse.model_validate(r) for r in new_insights]
        return InsightListResponse(items=items, total=len(items), page=1)
    except Exception as e:
        logger.error(f"[InsightsRouter] Generate weekly failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Insight generation failed: {str(e)}")


# ── A/B 实验 ──────────────────────────────────────────────────────────────────

@router.get("/experiments", response_model=ExperimentsListResponse, summary="A/B 实验列表")
async def list_experiments(
    status: str | None = Query(default=None, description="RUNNING / COMPLETED / FAILED"),
    limit:  int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_session),
):
    """查询 A/B 参数实验列表。"""
    rows = await ab_test_engine.list_experiments(db, status=status, limit=limit)
    items = [ABExperimentItemResponse.model_validate(r) for r in rows]
    return ExperimentsListResponse(items=items, total=len(items))


@router.post("/experiments", response_model=ABExperimentItemResponse, status_code=201, summary="新建 A/B 实验")
async def create_experiment(
    body: CreateExperimentRequest,
    db: AsyncSession = Depends(get_session),
):
    """创建一个新的参数 A/B 测试实验（时长默认 14 天）。"""
    exp = await ab_test_engine.create_experiment(
        db,
        insight_id=body.insight_id,
        experiment_name=body.experiment_name,
        param_key=body.param_key,
        control_value=body.control_value,
        treatment_value=body.treatment_value,
        duration_days=body.duration_days,
    )
    return ABExperimentItemResponse.model_validate(exp)
