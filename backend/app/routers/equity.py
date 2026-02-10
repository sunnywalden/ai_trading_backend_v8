"""V9: 资金曲线路由"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.core.config import settings
from app.broker.factory import make_option_broker_client
from app.services.equity_service import EquityService
from app.schemas.equity import EquitySnapshotsResponse, EquitySnapshotView, PnlAttributionResponse, PnlAttributionItem

router = APIRouter(prefix="/equity", tags=["V9-Equity"])


@router.get("/snapshots", response_model=EquitySnapshotsResponse)
async def get_equity_snapshots(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取权益曲线数据"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = EquityService(session)
    snapshots = await svc.get_snapshots(account_id, days)
    items = [
        EquitySnapshotView(
            snapshot_date=s.snapshot_date,
            total_equity=float(s.total_equity),
            cash=float(s.cash),
            market_value=float(s.market_value),
            daily_return=float(s.daily_return) if s.daily_return else None,
            cumulative_return=float(s.cumulative_return) if s.cumulative_return else None,
            max_drawdown_pct=float(s.max_drawdown_pct) if s.max_drawdown_pct else None,
            benchmark_return=float(s.benchmark_return) if s.benchmark_return else None,
        )
        for s in snapshots
    ]
    return EquitySnapshotsResponse(account_id=account_id, snapshots=items)


@router.get("/pnl-attribution", response_model=PnlAttributionResponse)
async def get_pnl_attribution(
    group_by: str = Query("symbol", description="归因维度: symbol, strategy"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取 PnL 归因"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = EquityService(session)
    data = await svc.get_pnl_attribution(account_id, group_by, start_date, end_date)
    items = [PnlAttributionItem(**d) for d in data]
    total_pnl = sum(d["pnl"] for d in data)
    return PnlAttributionResponse(
        account_id=account_id,
        group_by=group_by,
        total_pnl=total_pnl,
        items=items,
    )


@router.post("/snapshot")
async def create_snapshot(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """手动触发当日权益快照"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = EquityService(session)
    snap = await svc.create_daily_snapshot(account_id)
    return {"status": "ok", "snapshot_date": str(snap.snapshot_date), "total_equity": float(snap.total_equity)}
