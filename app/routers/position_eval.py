"""持仓评估任务管理 API 路由"""
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.broker.factory import make_option_broker_client
from app.services.position_eval_service import PositionEvalService
from app.schemas.position_eval import (
    PositionEvalConfigCreate,
    PositionEvalConfigUpdate,
    PositionEvalConfigView,
    PositionEvalConfigListResponse,
    PositionEvalTaskView,
    PositionEvalTaskDetailView,
    PositionEvalTaskListResponse,
    TriggerEvalTaskRequest,
    BatchDeleteTasksRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/position-eval", tags=["持仓评估任务"])


# ─── 账户工具 ───────────────────────────────────────────────
async def _get_account_id() -> str:
    broker = make_option_broker_client()
    return await broker.get_account_id()


# ═══════════════════════════════════════════════════════════
# 配置管理
# ═══════════════════════════════════════════════════════════

@router.get("/configs", response_model=PositionEvalConfigListResponse, summary="获取评估配置列表")
async def list_configs(
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    items = await svc.list_configs(account_id)
    return PositionEvalConfigListResponse(
        total=len(items),
        items=[PositionEvalConfigView.model_validate(i) for i in items],
    )


@router.post("/configs", response_model=PositionEvalConfigView, summary="创建评估配置")
async def create_config(
    body: PositionEvalConfigCreate,
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    config = await svc.create_config(account_id, body)
    return PositionEvalConfigView.model_validate(config)


@router.put("/configs/{config_id}", response_model=PositionEvalConfigView, summary="更新评估配置")
async def update_config(
    config_id: int,
    body: PositionEvalConfigUpdate,
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    config = await svc.update_config(account_id, config_id, body)
    if config is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    return PositionEvalConfigView.model_validate(config)


@router.delete("/configs/{config_id}", summary="删除评估配置")
async def delete_config(
    config_id: int,
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    ok = await svc.delete_config(account_id, config_id)
    if not ok:
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"status": "ok", "message": "配置已删除"}


# ═══════════════════════════════════════════════════════════
# 待执行任务管理
# ═══════════════════════════════════════════════════════════

@router.get("/tasks/pending", response_model=PositionEvalTaskListResponse, summary="获取待执行任务列表")
async def list_pending_tasks(
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    items = await svc.list_pending_tasks(account_id)
    return PositionEvalTaskListResponse(
        total=len(items),
        items=[PositionEvalTaskView.model_validate(t) for t in items],
    )


@router.post("/tasks", response_model=PositionEvalTaskView, summary="手动触发评估任务（创建待执行任务）")
async def trigger_task(
    body: TriggerEvalTaskRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    task = await svc.trigger_task(account_id, body)

    # 立即提交到后台执行
    async def _run():
        from app.models.db import SessionLocal
        async with SessionLocal() as bg_session:
            bg_svc = PositionEvalService(bg_session)
            try:
                await bg_svc.run_task(account_id, task.id)
            except Exception as exc:
                logger.exception("Background eval task %s failed: %s", task.id, exc)

    background_tasks.add_task(asyncio.ensure_future, _run())
    return PositionEvalTaskView.model_validate(task)


@router.delete("/tasks/pending", summary="批量删除待执行任务")
async def batch_delete_pending(
    body: BatchDeleteTasksRequest,
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    deleted = await svc.batch_delete_pending(account_id, body.task_ids)
    return {"status": "ok", "deleted": deleted}


# ═══════════════════════════════════════════════════════════
# 已执行任务历史
# ═══════════════════════════════════════════════════════════

@router.get("/tasks/history", response_model=PositionEvalTaskListResponse, summary="获取已执行任务列表")
async def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="筛选状态: DONE / FAILED / CANCELLED"),
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    total, items = await svc.list_history_tasks(account_id, page, page_size, status)
    return PositionEvalTaskListResponse(
        total=total,
        items=[PositionEvalTaskView.model_validate(t) for t in items],
    )


@router.get("/tasks/{task_id}", response_model=PositionEvalTaskDetailView, summary="获取任务详情（含逐标的结果）")
async def get_task_detail(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    _current_user: str = Depends(get_current_user),
):
    account_id = await _get_account_id()
    svc = PositionEvalService(session)
    task = await svc.get_task(account_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return PositionEvalTaskDetailView.model_validate(task)
