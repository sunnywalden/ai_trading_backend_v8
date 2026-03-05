"""V10.3.3 可观测性 2.0 API 路由

端点：
  GET  /api/v1/observability/execution-quality        — IS 四分解最近记录
  GET  /api/v1/observability/execution-quality/trend  — 日度 IS 趋势
  GET  /api/v1/observability/fill-heatmap             — 按 symbol×algo IS 热力图
  GET  /api/v1/observability/signal-intelligence      — 六维因子 IC + 拥挤度
  GET  /api/v1/observability/signal-correlation       — 标的信号相关矩阵
  GET  /api/v1/observability/crowding-alerts          — 拥挤度告警列表
  GET  /api/v1/observability/risk-cluster             — 完整风险仪表板
  GET  /api/v1/observability/factor-exposure          — 因子敞口历史
  GET  /api/v1/observability/correlation-alerts       — 相关性骤升历史
  POST /api/v1/observability/execution-quality/record — 手动记录执行质量（内部 hook）
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.broker.factory import make_option_broker_client
from app.services.execution_microscope_service import execution_microscope_service
from app.services.signal_intelligence_service import signal_intelligence_service
from app.services.risk_observability_service import risk_observability_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/observability", tags=["可观测性 2.0 V10.3.3"])


async def _resolve_observability_account_id(account_id: str | None, current_user: str) -> str:
    """统一账户解析：优先显式参数，其次券商实时账户，最后回退 current_user。"""
    if account_id:
        return str(account_id)
    try:
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            return str(broker_id)
    except Exception:
        pass
    return str(current_user)


# ─────────────────── Execution Microscope ──────────────────────────────────

@router.get("/execution-quality")
async def get_execution_quality(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最近 N 笔 IS 四分解执行质量记录。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await execution_microscope_service.get_quality_summary(db, resolved_account_id, limit=limit)


@router.get("/execution-quality/trend")
async def get_execution_quality_trend(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    days: int = Query(default=30, ge=1, le=90),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回按日聚合的平均 IS 趋势，用于折线图。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await execution_microscope_service.get_avg_is_by_date(db, resolved_account_id, days=days)


@router.get("/fill-heatmap")
async def get_fill_heatmap(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    days: int = Query(default=30, ge=1, le=90),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回 symbol × algo_type 平均 IS 热力图数据。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await execution_microscope_service.get_fill_heatmap(db, resolved_account_id, days=days)


# ─────────────────── Signal Intelligence Observatory ───────────────────────

@router.get("/signal-intelligence")
async def get_signal_intelligence(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回六维因子 IC 序列 + Alpha 半衰期 + 拥挤度状态。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await signal_intelligence_service.get_signal_intelligence(db, resolved_account_id)


@router.get("/signal-correlation")
async def get_signal_correlation(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    symbols: str = Query(default="", description="逗号分隔标的列表，空表示自动取 Top10"),
    days: int = Query(default=20, ge=5, le=60),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回标的间信号相关矩阵。"""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await signal_intelligence_service.get_signal_correlation_matrix(
        db, resolved_account_id, symbols=symbol_list, days=days
    )


@router.get("/crowding-alerts")
async def get_crowding_alerts(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回当前拥挤度超阈值 (>0.75) 的因子维度告警。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await signal_intelligence_service.get_crowding_alerts(db, resolved_account_id)


# ─────────────────── Risk Observability Cluster ────────────────────────────

@router.get("/risk-cluster")
async def get_risk_cluster(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回完整风险可观测仪表板（最新快照 + 24h 历史 + 告警）。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await risk_observability_service.get_risk_cluster(db, resolved_account_id)


@router.get("/factor-exposure")
async def get_factor_exposure(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最近 N 小时因子敞口时间序列。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await risk_observability_service.get_factor_exposure_history(db, resolved_account_id, hours=hours)


@router.get("/correlation-alerts")
async def get_correlation_alerts(
    account_id: str | None = Query(default=None, description="账户ID，不传则自动解析当前券商账户"),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回历史相关性骤升记录。"""
    resolved_account_id = await _resolve_observability_account_id(account_id, user_id)
    return await risk_observability_service.get_correlation_alerts(db, resolved_account_id, limit=limit)
