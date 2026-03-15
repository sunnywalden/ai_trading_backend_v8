"""V10.4.4 – Position & ExecutionSlice management API.

Prefix : /api/v1/pos
Tags   : Positions V2

Endpoints:
  GET  /api/v1/pos/                             – list active positions
  GET  /api/v1/pos/exceptions                   – positions in EXCEPTION status
  GET  /api/v1/pos/stuck-slices                 – stuck execution slices
  GET  /api/v1/pos/stats/closing-reasons        – closing reason distribution
  GET  /api/v1/pos/portfolio-summary            – counts for dashboard
  GET  /api/v1/pos/{id}                         – position detail + slices
  GET  /api/v1/pos/{id}/timeline                – lifecycle event timeline
  GET  /api/v1/pos/{id}/slices                  – execution slices
  POST /api/v1/pos/{id}/manual-close            – human-triggered close
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.account_context import require_account_access
from app.models.db import get_session
from app.services.broker_order_sync_service import reconcile_stale_closing_positions
from app.services.position_lifecycle_manager import PositionLifecycleManager
from app.services.position_query_service import PositionQueryService
from app.services.truth_source_service import truth_source_service

router = APIRouter(prefix="/api/v1/pos", tags=["Positions V2"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ManualCloseRequest(BaseModel):
    actor: str = "operator"
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Collection endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="活跃仓位列表")
async def list_active_positions(
    account_id: str = Depends(require_account_access("ANALYZE")),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """返回账户下当前活跃仓位（生产读侧优先使用券商真实持仓）。"""
    snapshot = await truth_source_service.get_positions_read_model(db, account_id)
    return list(snapshot.get("items") or [])


@router.get("/exceptions", summary="异常仓位列表")
async def list_exception_positions(
    account_id: str = Depends(require_account_access("ANALYZE")),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """返回处于 EXCEPTION 状态、需要人工处理的仓位。"""
    svc = PositionQueryService(db)
    return await svc.get_exception_positions(account_id)


@router.get("/stuck-slices", summary="卡单列表")
async def list_stuck_slices(
    account_id: str = Depends(require_account_access("ANALYZE")),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """返回所有 STUCK 状态的执行切片。"""
    svc = PositionQueryService(db)
    return await svc.get_stuck_slices(account_id)


@router.get("/stats/closing-reasons", summary="平仓原因分布")
async def closing_reason_stats(
    account_id: str = Depends(require_account_access("ANALYZE")),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """近 N 天平仓/强平原因分布。"""
    svc = PositionQueryService(db)
    return await svc.get_closing_reason_stats(account_id, days)


@router.get("/portfolio-summary", summary="组合摘要")
async def portfolio_summary(
    account_id: str = Depends(require_account_access("ANALYZE")),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """活跃仓位、异常仓位、卡单数量摘要，供仪表盘小组件使用。"""
    snapshot = await truth_source_service.get_positions_read_model(db, account_id)
    svc = PositionQueryService(db)
    lifecycle_summary = await svc.get_portfolio_summary(account_id)
    read_items = list(snapshot.get("items") or [])
    read_exception_positions = sum(
        1 for item in read_items if str(item.get("status") or "").upper() == "EXCEPTION"
    )
    return {
        **lifecycle_summary,
        "active_positions": int(snapshot.get("active_positions") or 0),
        "exception_positions": read_exception_positions,
        "active_positions_source": snapshot.get("source"),
        "broker_active_positions": int(snapshot.get("broker_active_positions") or 0),
        "lifecycle_active_positions": int(
            snapshot.get("lifecycle_active_positions") or 0
        ),
        "lifecycle_exception_positions": int(
            lifecycle_summary.get("exception_positions") or 0
        ),
        "mismatch_detected": bool(snapshot.get("mismatch_detected")),
        "mismatch_symbols": list(snapshot.get("mismatch_symbols") or []),
    }


@router.post("/reconcile-stale-closing", summary="手动收口卡在平仓中的仓位")
async def reconcile_closing_positions(
    account_id: str = Depends(require_account_access("OPERATE")),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """将券商已无真实持仓、但 Position 仍停留在 CLOSING 的仓位手动收口到 CLOSED。"""
    return await reconcile_stale_closing_positions(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Single-position endpoints
# ---------------------------------------------------------------------------


@router.get("/{position_id}", summary="仓位详情")
async def get_position(
    position_id: int,
    account_id: str = Depends(require_account_access("ANALYZE")),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """仓位详情（含执行切片列表）。"""
    svc = PositionQueryService(db)
    result = await svc.get_position_detail(position_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")
    if str(result.get("account_id") or "") != str(account_id):
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")
    return result


@router.get("/{position_id}/timeline", summary="生命周期事件时间线")
async def get_position_timeline(
    position_id: int,
    limit: int = Query(100, ge=1, le=500),
    account_id: str = Depends(require_account_access("ANALYZE")),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """倒序返回仓位生命周期事件（最多 500 条）。"""
    svc = PositionQueryService(db)
    detail = await svc.get_position_detail(position_id)
    if detail is None or str(detail.get("account_id") or "") != str(account_id):
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")
    return await svc.get_position_timeline(position_id, limit)


@router.get("/{position_id}/slices", summary="执行切片列表")
async def get_position_slices(
    position_id: int,
    account_id: str = Depends(require_account_access("ANALYZE")),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """返回仓位下所有执行切片。"""
    svc = PositionQueryService(db)
    detail = await svc.get_position_detail(position_id)
    if detail is None or str(detail.get("account_id") or "") != str(account_id):
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")
    return await svc.get_position_slices(position_id)


@router.post("/{position_id}/manual-close", summary="人工平仓")
async def manual_close(
    position_id: int,
    body: ManualCloseRequest,
    account_id: str = Depends(require_account_access("OPERATE")),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """触发人工平仓。创建 CLOSE ExecutionSlice，仓位状态切换至 CLOSING。"""
    plm = PositionLifecycleManager(db)
    try:
        detail = await PositionQueryService(db).get_position_detail(position_id)
        if detail is None or str(detail.get("account_id") or "") != str(account_id):
            raise HTTPException(
                status_code=404, detail=f"Position {position_id} not found"
            )
        slc = await plm.manual_close(
            position_id=position_id,
            actor=body.actor,
            note=body.note,
        )
        return {"position_id": position_id, "slice_id": slc.id, "status": "CLOSING"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
