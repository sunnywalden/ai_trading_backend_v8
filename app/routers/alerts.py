"""V9: 价格告警路由"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.broker.factory import make_option_broker_client
from app.services.alert_service import AlertService
from app.schemas.alerts import (
    AlertCreateRequest, AlertUpdateRequest, AlertView,
    AlertListResponse, AlertHistoryView, AlertHistoryResponse,
)

router = APIRouter(prefix="/alerts", tags=["V9-Alerts"])


@router.post("", response_model=AlertView)
async def create_alert(
    payload: AlertCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """创建告警规则"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
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
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = AlertService(session)
    alert = await svc.update_alert(alert_id, account_id, payload.model_dump(exclude_none=True))
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
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = AlertService(session)
    ok = await svc.delete_alert(alert_id, account_id)
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
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = AlertService(session)
    alerts = await svc.list_alerts(account_id, status)
    items = [AlertView.model_validate(a, from_attributes=True) for a in alerts]
    return AlertListResponse(items=items, total=len(items))


@router.get("/history", response_model=AlertHistoryResponse)
async def get_alert_history(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取告警触发历史"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = AlertService(session)
    history = await svc.get_history(account_id, limit)
    items = [AlertHistoryView.model_validate(h, from_attributes=True) for h in history]
    return AlertHistoryResponse(items=items, total=len(items))
