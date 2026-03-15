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
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.account_context import require_account_access
from app.models.db import get_session
from app.schemas.order_book import (
    OrderBookFilter,
    OrderBookResponse,
    OrderBookRow,
    OrderBookSummary,
    StopLossUpdateRequest,
    StopLossUpdateResponse,
)
from app.schemas.situational_awareness import (
    ActiveExecutionsBlock,
    ActiveFencesBlock,
    AutonomyBlock,
    PendingConfirmsBlock,
    RegimeBlock,
    SituationalAwarenessSnapshot,
    VarBlock,
)
from app.services.order_book_service import order_book_service
from app.services.read_models import get_order_book_workbench
from app.services.situational_awareness_service import situational_awareness_service

router = APIRouter(prefix="/api/v1/order-book", tags=["V10.3 智能订单簿"])
logger = logging.getLogger(__name__)
DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=OrderBookResponse, summary="全量订单视图")
async def list_orders(
    db: DbSession,
    resolved_account_id: Annotated[
        str,
        Depends(require_account_access("ANALYZE")),
    ],
    direction: Annotated[
        Optional[str],
        Query(description="BUY / SELL"),
    ] = None,
    market: Annotated[Optional[str], Query(description="US / HK / CN")] = None,
    plan_type: Annotated[Optional[str], Query()] = None,
    stage_min: Annotated[Optional[int], Query(ge=0, le=16)] = None,
    stage_max: Annotated[Optional[int], Query(ge=0, le=16)] = None,
    confidence_min: Annotated[Optional[float], Query(ge=0, le=100)] = None,
    confidence_max: Annotated[Optional[float], Query(ge=0, le=100)] = None,
    search: Annotated[Optional[str], Query(description="symbol 模糊搜索")] = None,
):
    """返回分 3 组的订单列表：活跃执行中 / 监控中 / 今日已完成。

    支持多维过滤，最多返回 500 条。
    """
    filters = OrderBookFilter(
        direction=direction,
        account_id=resolved_account_id,
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
    db: DbSession,
    account_id: Annotated[str, Depends(require_account_access("ANALYZE"))],
):
    """返回各状态计数、PnL 汇总、平均置信度等。"""
    workbench = await get_order_book_workbench(db, account_id)
    return workbench["summary"]


@router.get("/workbench", summary="V11.1.1 智能订单簿工作台聚合")
async def get_workbench(
    db: DbSession,
    account_id: Annotated[str, Depends(require_account_access("ANALYZE"))],
) -> dict[str, Any]:
    """返回订单簿主工作台所需的聚合读模型。"""
    return await get_order_book_workbench(db, account_id)


@router.get(
    "/{plan_id}/detail",
    response_model=OrderBookRow,
    summary="单笔订单详情",
    responses={404: {"description": "Order not found"}},
)
async def get_order_detail(
    plan_id: int,
    db: DbSession,
    account_id: Annotated[str, Depends(require_account_access("ANALYZE"))],
):
    """返回单笔订单完整详情，包含 provenance_snapshot。"""
    row = await order_book_service.get_order_detail(db, plan_id, account_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Order {plan_id} not found",
        )
    return row


@router.patch(
    "/{plan_id}/stop-loss",
    response_model=StopLossUpdateResponse,
    summary="修改止损价",
    responses={404: {"description": "Order not found"}},
)
async def update_stop_loss(
    plan_id: int,
    body: StopLossUpdateRequest,
    db: DbSession,
    account_id: Annotated[str, Depends(require_account_access("OPERATE"))],
):
    """修改指定订单的止损价，同时写入 FSM 转换日志。"""
    result = await order_book_service.update_stop_loss(
        db,
        plan_id,
        body.new_stop_loss,
        body.reason,
        account_id,
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Order {plan_id} not found",
        )
    return result


@router.get(
    "/situational-awareness",
    response_model=SituationalAwarenessSnapshot,
    summary="全局态势感知快照（REST轮询备用）",
)
async def get_situational_awareness(
    db: DbSession,
    account_id: Annotated[str, Depends(require_account_access("ANALYZE"))],
):
    """REST 轮询备用接口（推荐使用 WebSocket /api/v1/ws/situational-awareness）。"""
    del account_id
    try:
        return await asyncio.wait_for(
            situational_awareness_service.get_snapshot(db),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[OrderBook] situational-awareness snapshot timed out, "
            "returning degraded payload"
        )
    except (
        RuntimeError,
        ValueError,
        TypeError,
        LookupError,
        OSError,
        SQLAlchemyError,
    ) as exc:
        logger.warning(
            "[OrderBook] situational-awareness snapshot failed: %s",
            exc,
        )

    return SituationalAwarenessSnapshot(
        regime=RegimeBlock(),
        var=VarBlock(),
        active_fences=ActiveFencesBlock(),
        active_executions=ActiveExecutionsBlock(),
        pending_confirms=PendingConfirmsBlock(),
        autonomy=AutonomyBlock(),
        as_of=datetime.now(timezone.utc),
    )
