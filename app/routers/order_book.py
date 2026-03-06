"""V10.3: 智能订单簿 API Router

端点：
  GET  /api/v1/order-book                  — 全量订单视图（3分组）
  GET  /api/v1/order-book/summary          — 聚合汇总
  GET  /api/v1/order-book/{id}/detail      — 单笔完整详情
  PATCH /api/v1/order-book/{id}/stop-loss  — 修改止损
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.services.order_book_service import order_book_service
from app.schemas.order_book import (
    OrderBookResponse, OrderBookSummary, OrderBookRow,
    OrderBookFilter,
    StopLossUpdateRequest, StopLossUpdateResponse,
)
from app.schemas.situational_awareness import (
    SituationalAwarenessSnapshot,
    RegimeBlock,
    VarBlock,
    ActiveFencesBlock,
    ActiveExecutionsBlock,
    PendingConfirmsBlock,
    AutonomyBlock,
)
from app.services.situational_awareness_service import situational_awareness_service

router = APIRouter(prefix="/api/v1/order-book", tags=["V10.3 智能订单簿"])
logger = logging.getLogger(__name__)


@router.get("", response_model=OrderBookResponse, summary="全量订单视图")
async def list_orders(
    direction: Optional[str]   = Query(None, description="BUY / SELL"),
    account_id: Optional[str]  = Query(None),
    market: Optional[str]      = Query(None, description="US / HK / CN"),
    plan_type: Optional[str]   = Query(None),
    stage_min: Optional[int]   = Query(None, ge=0, le=16),
    stage_max: Optional[int]   = Query(None, ge=0, le=16),
    confidence_min: Optional[float] = Query(None, ge=0, le=100),
    confidence_max: Optional[float] = Query(None, ge=0, le=100),
    search: Optional[str]      = Query(None, description="symbol 模糊搜索"),
    db: AsyncSession = Depends(get_session),
):
    """返回分 3 组的订单列表：活跃执行中 / 监控中 / 今日已完成。

    支持多维过滤，最多返回 500 条。
    """
    filters = OrderBookFilter(
        direction=direction,
        account_id=account_id,
        market=market,
        plan_type=plan_type,
        stage_min=stage_min,
        stage_max=stage_max,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        search=search,
    )
    return await order_book_service.list_orders(db, filters)


@router.get("/summary", response_model=OrderBookSummary, summary="订单簿聚合汇总")
async def get_summary(
    db: AsyncSession = Depends(get_session),
):
    """返回各状态计数、PnL 汇总、平均置信度等。"""
    return await order_book_service.get_summary(db)


@router.get("/{plan_id}/detail", response_model=OrderBookRow, summary="单笔订单详情")
async def get_order_detail(
    plan_id: int,
    db: AsyncSession = Depends(get_session),
):
    """返回单笔订单完整详情，包含 provenance_snapshot。"""
    row = await order_book_service.get_order_detail(db, plan_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {plan_id} not found")
    return row


@router.patch("/{plan_id}/stop-loss", response_model=StopLossUpdateResponse, summary="修改止损价")
async def update_stop_loss(
    plan_id: int,
    body: StopLossUpdateRequest,
    db: AsyncSession = Depends(get_session),
):
    """修改指定订单的止损价，同时写入 FSM 转换日志。"""
    result = await order_book_service.update_stop_loss(
        db, plan_id, body.new_stop_loss, body.reason
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Order {plan_id} not found")
    return result


@router.get("/situational-awareness", response_model=SituationalAwarenessSnapshot, summary="全局态势感知快照（REST轮询备用）")
async def get_situational_awareness(
    db: AsyncSession = Depends(get_session),
):
    """REST 轮询备用接口（推荐使用 WebSocket /api/v1/ws/situational-awareness）。"""
    try:
        return await asyncio.wait_for(
            situational_awareness_service.get_snapshot(db),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[OrderBook] situational-awareness snapshot timed out, returning degraded payload")
    except Exception as exc:
        logger.warning("[OrderBook] situational-awareness snapshot failed: %s", exc)

    return SituationalAwarenessSnapshot(
        regime=RegimeBlock(),
        var=VarBlock(),
        active_fences=ActiveFencesBlock(),
        active_executions=ActiveExecutionsBlock(),
        pending_confirms=PendingConfirmsBlock(),
        autonomy=AutonomyBlock(),
        as_of=datetime.now(timezone.utc),
    )
