"""统一任务配置路由"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.schemas.task_config import (
    TaskTriggerConfigView,
    TaskTriggerConfigCreate,
    TaskTriggerConfigUpdate,
    TaskTriggerConfigList,
    TaskType,
)
from app.services.task_config_service import TaskTriggerConfigService
from app.core.config import settings

router = APIRouter(tags=["TaskConfig"])


@router.get("/task-configs", response_model=TaskTriggerConfigList)
async def list_task_configs(
    task_type: Optional[TaskType] = Query(None, description="过滤任务类型"),
    account_id: str = Query(settings.TIGER_ACCOUNT, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取所有任务触发配置列表"""
    svc = TaskTriggerConfigService(session)
    configs = await svc.list_configs(account_id=account_id, task_type=task_type)
    return TaskTriggerConfigList(
        configs=[TaskTriggerConfigView.model_validate(c) for c in configs],
        total=len(configs)
    )


@router.get("/task-configs/{config_id}", response_model=TaskTriggerConfigView)
async def get_task_config(
    config_id: int,
    account_id: str = Query(settings.TIGER_ACCOUNT, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取指定任务配置详情"""
    svc = TaskTriggerConfigService(session)
    config = await svc.get_config(account_id=account_id, config_id=config_id)
    if not config:
        raise HTTPException(status_code=404, detail="任务配置不存在")
    return config


@router.post("/task-configs", response_model=TaskTriggerConfigView)
async def create_task_config(
    data: TaskTriggerConfigCreate,
    account_id: str = Query(settings.TIGER_ACCOUNT, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """创建新任务触发配置"""
    svc = TaskTriggerConfigService(session)
    config = await svc.create_config(account_id=account_id, data=data)
    return config


@router.put("/task-configs/{config_id}", response_model=TaskTriggerConfigView)
async def update_task_config(
    config_id: int,
    data: TaskTriggerConfigUpdate,
    account_id: str = Query(settings.TIGER_ACCOUNT, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """编辑任务触发配置"""
    svc = TaskTriggerConfigService(session)
    config = await svc.update_config(account_id=account_id, config_id=config_id, data=data)
    if not config:
        raise HTTPException(status_code=404, detail="任务配置不存在")
    return config


@router.delete("/task-configs/{config_id}")
async def delete_task_config(
    config_id: int,
    account_id: str = Query(settings.TIGER_ACCOUNT, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """删除任务触发配置"""
    svc = TaskTriggerConfigService(session)
    success = await svc.delete_config(account_id=account_id, config_id=config_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务配置不存在")
    return {"message": "任务配置已删除", "id": config_id, "success": True}


@router.post("/task-configs/{config_id}/toggle", response_model=TaskTriggerConfigView)
async def toggle_task_config(
    config_id: int,
    enabled: bool,
    account_id: str = Query(settings.TIGER_ACCOUNT, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """启停任务触发配置"""
    svc = TaskTriggerConfigService(session)
    config = await svc.toggle_enabled(account_id=account_id, config_id=config_id, enabled=enabled)
    if not config:
        raise HTTPException(status_code=404, detail="任务配置不存在")
    return config
