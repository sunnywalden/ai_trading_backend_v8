"""V10.2-M5: 交易归因 API 路由

Endpoints:
  GET  /api/v1/attribution/trades   → 分页查询历史归因记录
  GET  /api/v1/attribution/summary  → 归因统计汇总（WIN/LOSS 分布）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.models.trade_attribution import TradeAttributionEntry
from app.schemas.attribution import (
    AttributionSummaryResponse,
    TradeAttributionItemResponse,
    TradeAttributionListResponse,
)
from app.services.trade_attribution_engine import trade_attribution_engine

router = APIRouter(prefix="/api/v1/attribution", tags=["Attribution"])


@router.get("/trades", response_model=TradeAttributionListResponse, summary="历史归因记录")
async def list_attribution_trades(
    limit:    int = Query(default=20, ge=1, le=100),
    offset:   int = Query(default=0,  ge=0),
    symbol:   str | None = Query(default=None),
    category: str | None = Query(default=None, description="WIN / LOSS / BREAKEVEN"),
    db: AsyncSession = Depends(get_session),
):
    """分页获取历史交易归因分析记录。"""
    stmt = select(TradeAttributionEntry).order_by(TradeAttributionEntry.created_at.desc())
    if symbol:
        stmt = stmt.where(TradeAttributionEntry.symbol == symbol)
    if category:
        stmt = stmt.where(TradeAttributionEntry.category == category)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one_or_none() or 0

    rows = list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())
    items = [TradeAttributionItemResponse.model_validate(r) for r in rows]
    return TradeAttributionListResponse(items=items, total=total)


@router.get("/summary", response_model=AttributionSummaryResponse, summary="归因统计汇总")
async def attribution_summary(
    days: int = Query(default=30, ge=7, le=365),
    db: AsyncSession  = Depends(get_session),
):
    """返回最近 N 天的归因分类统计（WIN / LOSS / BREAKEVEN 计数 + 平均分）。"""
    data = await trade_attribution_engine.get_summary(db, days=days)
    return AttributionSummaryResponse(**data)
