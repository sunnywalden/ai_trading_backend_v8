"""V10.3.3 War Room（战情室）API 路由

端点：
  GET  /api/v1/war-room/snapshot          — 一次返回全部面板数据
  GET  /api/v1/war-room/pnl-ticker        — P&L Ticker 聚合
  GET  /api/v1/war-room/intelligence-feed — Intelligence Feed（urgency 排序）
  GET  /api/v1/war-room/exposure          — 持仓热力图 + 因子敞口
  GET  /api/v1/war-room/alerts            — 智能告警列表
  PATCH /api/v1/war-room/alerts/{alert_id} — 告警状态更新（ack/dismiss）
  GET  /api/v1/war-room/alerts/stats      — 告警统计
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.broker.factory import make_option_broker_client
from app.services.war_room_service import war_room_service
from app.services.smart_alert_service import smart_alert_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/war-room", tags=["War Room V10.3.3"])


async def _resolve_broker_account_id(current_user: str) -> str:
    """券商账号解析：优先实时获取券商账号，回退 current_user。"""
    try:
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            return str(broker_id)
    except Exception:
        pass
    return str(current_user)


@router.get("/snapshot")
async def get_war_room_snapshot(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """一次调用返回所有战情室面板数据（P&L + Feed + Exposure）。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await war_room_service.get_war_room_snapshot(db, account_id)


@router.get("/pnl-ticker")
async def get_pnl_ticker(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回 P&L Ticker：total_pnl / pnl_change_1h / top_contributor / top_detractor。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await war_room_service.get_pnl_ticker(db, account_id)


@router.get("/intelligence-feed")
async def get_intelligence_feed(
    limit: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None, description="DECISION/RISK/EVENT/SIGNAL"),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回按 urgency_score 排序的 Intelligence Feed。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await war_room_service.get_intelligence_feed(
        db, account_id, limit=limit, category_filter=category
    )


@router.get("/exposure")
async def get_portfolio_exposure(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回持仓热力图数据 + 最新五因子敞口。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await war_room_service.get_portfolio_exposure(db, account_id)


@router.get("/alerts")
async def get_alerts(
    grade: str | None = Query(default=None, description="CRITICAL/HIGH/MEDIUM/LOW"),
    include_dismissed: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
):
    """返回智能告警列表（按级别优先级排序）。"""
    return smart_alert_service.get_alerts(
        user_id,
        grade_filter=grade,
        include_dismissed=include_dismissed,
        limit=limit,
    )


@router.get("/alerts/stats")
async def get_alert_stats(
    user_id: str = Depends(get_current_user),
):
    """返回告警统计：各级别数量 + action_required 数量。"""
    return smart_alert_service.get_alert_stats(user_id)


class AlertActionRequest(BaseModel):
    action: Literal["acknowledge", "dismiss"]


@router.patch("/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    body: AlertActionRequest,
    user_id: str = Depends(get_current_user),
):
    """确认或消除一条告警。"""
    if body.action == "acknowledge":
        result = smart_alert_service.acknowledge_alert(user_id, alert_id)
    else:
        result = smart_alert_service.dismiss_alert(user_id, alert_id)

    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return {"message": f"Alert {alert_id} {body.action}d", "alert": result}
