"""V9: 价格告警路由"""
from typing import Optional
import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.core.config import settings
from app.broker.factory import make_option_broker_client
from app.services.alert_service import AlertService
from app.schemas.alerts import (
    AlertCreateRequest, AlertUpdateRequest, AlertView,
    AlertListResponse, AlertHistoryView, AlertHistoryResponse,
)

router = APIRouter(prefix="/alerts", tags=["V9-Alerts"])
logger = logging.getLogger(__name__)


async def _resolve_account_ids(current_user: str) -> tuple[str, list[str]]:
    """返回主 account_id（用于新写入）与兼容查询 account_id 列表。"""
    primary = current_user
    ids: list[str] = []
    if current_user:
        ids.append(current_user)

    try:
        broker = make_option_broker_client()
        broker_account = await broker.get_account_id()
        if broker_account and broker_account not in ids:
            ids.append(broker_account)
    except Exception as e:
        logger.warning("[Alerts] broker account resolve failed, fallback to current_user only: %s", e)

    cfg_account = getattr(settings, "TIGER_ACCOUNT", None)
    if cfg_account and cfg_account not in ids:
        ids.append(cfg_account)

    return primary, ids


@router.post("", response_model=AlertView)
async def create_alert(
    payload: AlertCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """创建告警规则"""
    account_id, _ = await _resolve_account_ids(current_user)
    svc = AlertService(session)
    alert = await svc.create_alert(account_id, payload.model_dump(exclude_none=True))
    return AlertView.model_validate(alert, from_attributes=True)


@router.put("/{alert_id}", response_model=AlertView)
async def update_alert(
    alert_id: int,
    payload: AlertUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """更新告警规则"""
    account_id, account_ids = await _resolve_account_ids(current_user)
    svc = AlertService(session)
    alert = await svc.update_alert(
        alert_id,
        account_id,
        payload.model_dump(exclude_none=True),
        account_ids=account_ids,
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertView.model_validate(alert, from_attributes=True)


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """删除告警规则"""
    account_id, account_ids = await _resolve_account_ids(current_user)
    svc = AlertService(session)
    ok = await svc.delete_alert(alert_id, account_id, account_ids=account_ids)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "ok"}


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取告警列表"""
    account_id, account_ids = await _resolve_account_ids(current_user)
    svc = AlertService(session)
    alerts = await svc.list_alerts(account_id, status, account_ids=account_ids)
    items = [AlertView.model_validate(a, from_attributes=True) for a in alerts]
    return AlertListResponse(alerts=items, total=len(items))


@router.get("/history", response_model=AlertHistoryResponse)
async def get_alert_history(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取告警触发历史"""
    account_id, account_ids = await _resolve_account_ids(current_user)
    svc = AlertService(session)
    history = await svc.get_history(account_id, limit, account_ids=account_ids)
    items = [AlertHistoryView.model_validate(h, from_attributes=True) for h in history]
    return AlertHistoryResponse(history=items, total=len(items))
