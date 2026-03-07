"""V10.2-M2: 事件日历 API 路由

Endpoints:
  GET  /api/v1/events/calendar          → 获取未来 N 天事件列表
  GET  /api/v1/events/earnings-fence    → 获取当前所有活跃财报围栏
  POST /api/v1/events/override-fence    → 人工覆盖围栏
  POST /api/v1/events/earnings-result   → 录入财报实际数据
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.schemas.events import (ActiveFencesResponse,
                                EarningsFenceStatusResponse,
                                EarningsResultResponse,
                                EventCalendarListResponse,
                                OverrideFenceRequest,
                                RecordEarningsResultRequest)
from app.services.earnings_fence_service import earnings_fence_service
from app.services.event_calendar_service import event_calendar_service

router = APIRouter(prefix="/api/v1/events", tags=["Events"])


@router.get("/calendar", response_model=EventCalendarListResponse, summary="获取事件日历")
async def get_calendar(
    days:   int = Query(default=7,  ge=1, le=30, description="向前看 N 天"),
    symbol: Optional[str] = Query(default=None, description="可选：按股票代码过滤"),
    db: AsyncSession = Depends(get_session),
):
    """获取未来 N 天的市场事件列表（财报 / FOMC / NFP / CPI 等）。"""
    entries = await event_calendar_service.get_upcoming(db, days=days, symbol=symbol)
    from app.schemas.events import EventCalendarItemResponse
    items = [EventCalendarItemResponse.model_validate(e) for e in entries]
    return EventCalendarListResponse(items=items, total=len(items), days=days)


@router.get(
    "/earnings-fence",
    response_model=ActiveFencesResponse,
    summary="获取活跃财报围栏",
)
async def get_active_fences(db: AsyncSession = Depends(get_session)):
    """返回当前所有处于围栏保护状态的持仓资产列表。"""
    raw = await earnings_fence_service.get_active_fences(db)
    fences = [
        EarningsFenceStatusResponse(
            symbol=r["symbol"],
            active=True,
            reason=f"earnings on {r['event_date'][:10]}",
            event_id=r["event_id"],
            event_date=r["event_date"],
            max_size_pct=r["max_size_pct"],
            overridden=False,
        )
        for r in raw
    ]
    return ActiveFencesResponse(fences=fences)


@router.get(
    "/earnings-fence/{symbol}",
    response_model=EarningsFenceStatusResponse,
    summary="查询指定股票围栏状态",
)
async def get_fence_status(symbol: str, db: AsyncSession = Depends(get_session)):
    """查询特定股票的当前围栏状态（是否处于财报保护）。"""
    status = await earnings_fence_service.get_fence_status(db, symbol)
    return EarningsFenceStatusResponse(
        symbol=symbol,
        active=status.active,
        reason=status.reason,
        event_id=status.event_id,
        event_date=status.event_date,
        max_size_pct=status.max_size_pct,
        overridden=status.overridden,
        override_reason=status.override_reason,
    )


@router.post("/override-fence", summary="人工覆盖围栏")
async def override_fence(
    body: OverrideFenceRequest,
    db: AsyncSession = Depends(get_session),
):
    """由运营员工覆盖自动财报围栏。需提供覆盖原因。"""
    ok = await earnings_fence_service.override_fence(db, body.event_id, body.reason)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Event {body.event_id} not found")
    return {"success": True, "message": f"Fence override applied for event {body.event_id}"}


@router.post("/earnings-result", response_model=EarningsResultResponse, summary="录入财报实际结果")
async def record_earnings_result(
    body: RecordEarningsResultRequest,
    db: AsyncSession = Depends(get_session),
):
    """POST 财报实际 EPS 和营收，触发事后仓位重评估。"""
    await earnings_fence_service.record_earnings_result(
        db,
        symbol=body.symbol,
        eps_actual=body.eps_actual,
        revenue_actual=body.revenue_actual,
        notes=body.notes,
    )
    return EarningsResultResponse(success=True, message=f"Earnings result recorded for {body.symbol}")
