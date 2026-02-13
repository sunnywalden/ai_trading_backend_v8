from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
import asyncio
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.auth import get_current_user
from app.models.db import get_session
from app.jobs.scheduler import add_job
from app.jobs.strategy_jobs import execute_strategy_run_job
from app.services.strategy_export_service import StrategyExportService
from app.services.strategy_service import StrategyService, StrategyRunService
from app.schemas.strategy import (
    StrategyListResponse,
    StrategyDetailResponse,
    StrategySummaryView,
    StrategyDetailView,
    StrategyCreateRequest,
    StrategyUpdateParamsRequest,
    StrategyRunRequest,
    StrategyRunResponse,
    StrategyRunStatusView,
    StrategyRunLatestResponse,
    StrategyRunHistoryResponse,
    StrategyRunHistoryView,
    StrategyRunResultsResponse,
    StrategyExportResponse,
    StrategyRunAssetView,
)
from app.schemas.quick_trade import (
    QuickTradeRequest,
    QuickTradeResponse,
    QuickTradePreview,
    BatchQuickTradeRequest,
    BatchQuickTradeResponse,
)
from app.services.quick_trade_service import QuickTradeService

router = APIRouter()


def _ensure_permission(current_user: str, action: str) -> None:
    if not settings.AUTH_ENABLED:
        return
    allowed = settings.STRATEGY_EXECUTE_USERS if action == "execute" else settings.STRATEGY_MANAGE_USERS
    if current_user not in allowed:
        raise HTTPException(status_code=403, detail="Permission denied for strategy operation")


def _to_summary(strategy) -> StrategySummaryView:
    return StrategySummaryView(
        id=strategy.id,
        name=strategy.name,
        style=strategy.style,
        description=strategy.description,
        is_builtin=strategy.is_builtin,
        is_active=strategy.is_active,
        tags=strategy.tags or [],
        last_run_status=strategy.last_run_status,
        last_run_at=strategy.last_run_at,
    )


def _to_detail(strategy) -> StrategyDetailView:
    base = _to_summary(strategy).dict()
    return StrategyDetailView(
        **base,
        version=strategy.version,
        default_params=strategy.default_params or {},
        signal_sources=strategy.signal_sources or {},
        risk_profile=strategy.risk_profile or {},
    )


def _progress_from_status(status: str) -> int:
    mapping = {
        "QUEUED": 10,
        "EXECUTING": 60,
        "COMPLETED": 100,
        "FAILED": 100,
        "CANCELLED": 100,
    }
    return mapping.get(status.upper(), 0)


def _to_status_view(run) -> StrategyRunStatusView:
    history = run.history
    timeline = history.timeline if history else None
    return StrategyRunStatusView(
        run_id=run.id,
        status=run.status,
        phase=run.status,
        progress=_progress_from_status(run.status),
        attempt=run.attempt,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        timeline=timeline,
        direction=run.direction,
        target_universe=run.target_universe,
        min_score=run.min_score,
        max_results=run.max_results,
        priority=run.priority,
    )


def _to_history_item(run) -> StrategyRunHistoryView:

    history = run.history
    return StrategyRunHistoryView(
        run_id=run.id,
        strategy_id=run.strategy_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        hits=history.hits if history else None,
        hit_rate=history.hit_rate if history else None,
        avg_signal_strength=history.avg_signal_strength if history else None,
    )


def _to_results_view(run) -> StrategyRunResultsResponse:
    assets = [
        StrategyRunAssetView(
            symbol=asset.symbol,
            signal_strength=asset.signal_strength,
            weight=asset.weight,
            action=asset.action,
            direction=asset.direction,
            risk_flags=asset.risk_flags or [],
            notes=asset.notes,
            signal_dimensions=asset.signal_dimensions or {},
        )
        for asset in run.assets or []
    ]
    return StrategyRunResultsResponse(
        status="ok",
        run_id=run.id,
        strategy_id=run.strategy_id,
        assets=assets,
    )


@router.get("/strategies", response_model=StrategyListResponse)
async def list_strategies(
    style: Optional[str] = Query(None),
    is_builtin: Optional[bool] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    svc = StrategyService(session)
    strategies = await svc.list_strategies(style=style, is_builtin=is_builtin, limit=limit, offset=offset, search=search)
    return StrategyListResponse(strategies=[_to_summary(s) for s in strategies])


@router.get("/strategies/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy_detail(
    strategy_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    svc = StrategyService(session)
    strategy = await svc.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return StrategyDetailResponse(strategy=_to_detail(strategy))


@router.post("/strategies", response_model=StrategyDetailResponse)
async def create_strategy(
    payload: StrategyCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    _ensure_permission(current_user, "manage")
    svc = StrategyService(session)
    strategy = await svc.create_strategy(payload.model_dump(), owner_id=current_user)
    return StrategyDetailResponse(strategy=_to_detail(strategy))


@router.patch("/strategies/{strategy_id}/params", response_model=StrategyDetailResponse)
async def update_strategy_params(
    strategy_id: str,
    payload: StrategyUpdateParamsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    _ensure_permission(current_user, "manage")
    svc = StrategyService(session)
    strategy = await svc.update_strategy_params(strategy_id, payload.default_params)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return StrategyDetailResponse(strategy=_to_summary(strategy).model_copy(update={
        "version": strategy.version,
        "default_params": strategy.default_params or {},
        "signal_sources": strategy.signal_sources or {},
        "risk_profile": strategy.risk_profile or {},
    }))


@router.post("/strategies/{strategy_id}/run", response_model=StrategyRunResponse)
async def run_strategy(
    strategy_id: str,
    req: StrategyRunRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    _ensure_permission(current_user, "execute")
    strategy_svc = StrategyService(session)
    strategy = await strategy_svc.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    run_svc = StrategyRunService(session)
    run = await run_svc.create_run(
        strategy=strategy,
        user_id=current_user,
        account_id=req.account_id or settings.TIGER_ACCOUNT,
        direction=req.direction,
        notify_channels=req.notify_channels,
        target_universe=req.target_universe,
        min_score=req.min_score,
        max_results=req.max_results,
        priority=req.priority,
    )
    task_id = f"strategy_run:{run.id}"
    await run_svc.assign_task_id(run.id, task_id)

    try:
        if settings.ENABLE_SCHEDULER:
            # 使用上海时区以确保与调度器配置一致，避免 misfire
            run_date = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(seconds=2)
            add_job(
                func=execute_strategy_run_job,
                trigger="date",
                id=task_id,
                name=f"strategy_execution_{strategy.name}",
                run_date=run_date,
                args=(run.id, task_id),
            )
        else:
            asyncio.create_task(execute_strategy_run_job(run.id, task_id))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to schedule strategy run: {exc}")

    return StrategyRunResponse(run_id=run.id, celery_task_id=task_id)


@router.get("/strategy-runs/{run_id}/status", response_model=StrategyRunStatusView)
async def get_strategy_run_status(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    svc = StrategyRunService(session)
    run = await svc.get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Strategy run not found")
    return _to_status_view(run)


@router.get("/strategy-runs/latest", response_model=StrategyRunLatestResponse)
async def get_latest_strategy_run(
    account_id: Optional[str] = Query(None),
    strategy_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    svc = StrategyRunService(session)
    run = await svc.get_latest_run(account_id=account_id, strategy_id=strategy_id)
    if not run:
        return StrategyRunLatestResponse(run=None)
    return StrategyRunLatestResponse(run=_to_status_view(run))


@router.get("/strategy-runs", response_model=StrategyRunHistoryResponse)
async def list_strategy_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    strategy_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    svc = StrategyRunService(session)
    runs = await svc.list_runs(limit=limit, offset=offset, strategy_id=strategy_id, account_id=account_id, status=status)
    return StrategyRunHistoryResponse(runs=[_to_history_item(r) for r in runs])


@router.get("/strategy-runs/{run_id}/results", response_model=StrategyRunResultsResponse)
async def get_strategy_run_results(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    svc = StrategyRunService(session)
    run = await svc.get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Strategy run not found")
    return _to_results_view(run)


@router.post("/strategy-runs/{run_id}/export", response_model=StrategyExportResponse)
async def export_strategy_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    svc = StrategyRunService(session)
    run = await svc.get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Strategy run not found")
    export_service = StrategyExportService(session)
    try:
        result = await export_service.export_run_to_csv(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return StrategyExportResponse(run_id=run.id, **result)


@router.get("/strategy-runs/{run_id}/assets/{symbol}/preview", response_model=QuickTradeResponse)
async def preview_quick_trade(
    run_id: str,
    symbol: str,
    risk_budget: Optional[float] = Query(None, description="风险预算（账户权益占比）"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """预览快捷交易参数（不创建信号）"""
    svc = QuickTradeService(session)
    try:
        preview_data = await svc.preview_quick_trade(run_id, symbol, risk_budget)
        return QuickTradeResponse(
            status="ok",
            message="预览成功",
            preview=QuickTradePreview(**preview_data)
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预览失败: {str(e)}")


@router.post("/strategy-runs/{run_id}/assets/{symbol}/quick-trade", response_model=QuickTradeResponse)
async def execute_quick_trade(
    run_id: str,
    symbol: str,
    payload: QuickTradeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """从策略结果快速创建并执行交易"""
    _ensure_permission(current_user, "execute")
    svc = QuickTradeService(session)
    
    try:
        override_params = {
            "override_direction": payload.override_direction,
            "override_quantity": payload.override_quantity,
            "override_price": payload.override_price,
            "override_stop_loss": payload.override_stop_loss,
            "override_take_profit": payload.override_take_profit,
            "risk_budget": payload.risk_budget,
        }
        
        result = await svc.execute_quick_trade(
            run_id=run_id,
            symbol=symbol,
            execution_mode=payload.execution_mode.value,
            override_params=override_params,
            notes=payload.notes
        )
        
        return QuickTradeResponse(
            status=result["status"],
            signal_id=result.get("signal_id"),
            order_id=result.get("order_id"),
            message=result["message"],
            preview=QuickTradePreview(**result["preview"]) if "preview" in result else None
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")


@router.post("/strategy-runs/{run_id}/batch-quick-trade", response_model=BatchQuickTradeResponse)
async def batch_quick_trade(
    run_id: str,
    payload: BatchQuickTradeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """批量快捷交易"""
    _ensure_permission(current_user, "execute")
    svc = QuickTradeService(session)
    
    try:
        result = await svc.batch_quick_trade(
            run_id=run_id,
            symbols=payload.asset_symbols,
            execution_mode=payload.execution_mode.value,
            position_sizing_method=payload.position_sizing_method.value,
            custom_weights=payload.custom_weights,
            total_risk_budget=payload.total_risk_budget,
            notes=payload.notes
        )
        
        return BatchQuickTradeResponse(
            status="ok",
            total_signals=result["total_signals"],
            success_count=result["success_count"],
            failed_count=result["failed_count"],
            signal_ids=result["signal_ids"],
            failures=result["failures"],
            message=f"批量交易完成: {result['success_count']} 成功, {result['failed_count']} 失败"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量交易失败: {str(e)}")
