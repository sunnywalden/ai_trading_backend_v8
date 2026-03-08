"""live_safety.py — V10.5.1 M4: Live Safety & Model Degradation Guard

路由：
  GET /api/v1/live-safety/degradation   — 模型/执行/数据退化报告
  GET /api/v1/live-safety/freshness     — 数据陈旧度矩阵
  GET /api/v1/live-safety/throttle      — 自主度节流状态（综合推荐）

所有端点需要认证（Bearer Token）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.autonomy_throttle_service import autonomy_throttle_service
from app.services.data_freshness_guard_service import \
    data_freshness_guard_service
from app.services.model_degradation_monitor_service import \
    model_degradation_monitor_service

router = APIRouter(prefix="/api/v1/live-safety", tags=["V10.5.1-LiveSafety"])


async def _resolve_account_id(current_user: str) -> str:
    try:
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            return str(broker_id)
    except Exception:
        pass
    return str(current_user)


@router.get("/degradation")
async def get_degradation_report(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """模型退化监控报告。

    检测策略命中率漂移、置信度校准漂移、执行成本漂移和券商拒绝率突增，
    分别标记为 OK / WARNING / CRITICAL，并给出综合风险等级。
    """
    account_id = await _resolve_account_id(user_id)
    return await model_degradation_monitor_service.get_degradation_report(
        db, account_id
    )


@router.get("/freshness")
async def get_freshness_matrix(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """数据陈旧度矩阵。

    检测行情数据、仓位数据、事件日历、因子快照、市场体制共五类数据源的陈旧度，
    并给出推荐动作（NONE / DEGRADE_TO_SEMI / FREEZE_NEW_OPEN）。
    """
    account_id = await _resolve_account_id(user_id)
    return await data_freshness_guard_service.get_freshness_matrix(db, account_id)


@router.get("/throttle")
async def get_throttle_status(
    current_level: str = Query(
        default="FULL",
        description="系统当前实际自主度级别（FULL/SEMI/ADVISORY/FREEZE）",
    ),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """综合自主度节流状态。

    融合模型退化与数据陈旧度两个维度，输出推荐自主度级别、是否需要降级/升级、
    降级原因，以及各子报告的摘要。供前端安全面板与 Autonomy 页消费。
    """
    account_id = await _resolve_account_id(user_id)
    return await autonomy_throttle_service.get_throttle_status(
        db, account_id, current_autonomy_level=current_level.upper()
    )
