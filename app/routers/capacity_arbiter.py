"""V10.5.2: 席位竞争仲裁 API 路由

Endpoints:
  GET  /api/v1/capacity/config          → 查看容量仲裁配置
  PATCH /api/v1/capacity/config         → 热更新配置（运行时生效）
  POST /api/v1/capacity/preview         → dry-run 仲裁预演
  GET  /api/v1/capacity/logs            → 仲裁决策日志列表
  GET  /api/v1/capacity/logs/{log_id}   → 单条日志详情
  GET  /api/v1/capacity/stats           → 仲裁指标摘要
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.schemas.capacity_arbiter import (
    CandidateSnapshot,
    CapacityConfigPatchRequest,
    CapacityConfigResponse,
    CapacityLogDetailResponse,
    CapacityLogItem,
    CapacityLogListResponse,
    CapacityPreviewRequest,
    CapacityPreviewResponse,
    CapacityStatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/capacity", tags=["Capacity Arbiter (V10.5.2)"])


# ─────────────────────────────────────────────────────────────────────────────
# 配置查看 / 热更新
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/config", summary="查看席位竞争仲裁配置", response_model=CapacityConfigResponse
)
async def get_capacity_config(_user: str = Depends(get_current_user)):
    """返回当前有效的容量仲裁参数（含运行时覆盖值）。"""
    from app.services.signal_quality_config import get_signal_quality_config

    cfg = get_signal_quality_config()
    return CapacityConfigResponse(
        capacity_replacement_enabled=cfg.CAPACITY_REPLACEMENT_ENABLED,
        capacity_replacement_dry_run=cfg.CAPACITY_REPLACEMENT_DRY_RUN,
        capacity_replacement_max_per_cycle=cfg.CAPACITY_REPLACEMENT_MAX_PER_CYCLE,
        capacity_replacement_min_edge=cfg.CAPACITY_REPLACEMENT_MIN_EDGE,
        capacity_min_hold_minutes=cfg.CAPACITY_MIN_HOLD_MINUTES,
        capacity_replacement_cooldown_minutes=cfg.CAPACITY_REPLACEMENT_COOLDOWN_MINUTES,
        max_concurrent_positions=cfg.MAX_CONCURRENT_POSITIONS,
    )


@router.patch("/config", summary="热更新席位竞争配置（重启后恢复默认）")
async def patch_capacity_config(
    body: CapacityConfigPatchRequest,
    _user: str = Depends(get_current_user),
):
    """运行时热更新容量仲裁参数，不需要重启服务。"""
    from app.services.signal_quality_config import apply_runtime_override

    updates: dict = {}
    if body.capacity_replacement_enabled is not None:
        updates["CAPACITY_REPLACEMENT_ENABLED"] = body.capacity_replacement_enabled
    if body.capacity_replacement_dry_run is not None:
        updates["CAPACITY_REPLACEMENT_DRY_RUN"] = body.capacity_replacement_dry_run
    if body.capacity_replacement_max_per_cycle is not None:
        updates["CAPACITY_REPLACEMENT_MAX_PER_CYCLE"] = (
            body.capacity_replacement_max_per_cycle
        )
    if body.capacity_replacement_min_edge is not None:
        updates["CAPACITY_REPLACEMENT_MIN_EDGE"] = body.capacity_replacement_min_edge
    if body.capacity_min_hold_minutes is not None:
        updates["CAPACITY_MIN_HOLD_MINUTES"] = body.capacity_min_hold_minutes
    if body.capacity_replacement_cooldown_minutes is not None:
        updates["CAPACITY_REPLACEMENT_COOLDOWN_MINUTES"] = (
            body.capacity_replacement_cooldown_minutes
        )

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    new_cfg = apply_runtime_override(updates)
    logger.info("[CapacityRouter] Config updated: %s", list(updates.keys()))
    return {
        "updated_fields": list(updates.keys()),
        "capacity_replacement_enabled": new_cfg.CAPACITY_REPLACEMENT_ENABLED,
        "capacity_replacement_dry_run": new_cfg.CAPACITY_REPLACEMENT_DRY_RUN,
        "capacity_replacement_max_per_cycle": new_cfg.CAPACITY_REPLACEMENT_MAX_PER_CYCLE,
        "capacity_replacement_min_edge": new_cfg.CAPACITY_REPLACEMENT_MIN_EDGE,
        "capacity_min_hold_minutes": new_cfg.CAPACITY_MIN_HOLD_MINUTES,
        "capacity_replacement_cooldown_minutes": new_cfg.CAPACITY_REPLACEMENT_COOLDOWN_MINUTES,
    }


# ─────────────────────────────────────────────────────────────────────────────
# dry-run 仲裁预演
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/preview", summary="席位竞争 dry-run 预演", response_model=CapacityPreviewResponse
)
async def preview_capacity_arbitration(
    body: CapacityPreviewRequest,
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    """
    对指定账户当前的持仓 + 待处理 ENTRY 信号执行 dry-run 席位竞争预演。
    不触发任何实际平仓或拒绝操作；结果仅供观察。
    """
    from app.engine.position_monitor import PositionMonitor
    from app.models.trading_signal import SignalStatus, SignalType, TradingSignal
    from app.services.capacity_arbiter import capacity_arbiter_service
    from app.services.signal_quality_config import get_regime_adjusted_config

    # 获取当前持仓快照
    try:
        monitor = PositionMonitor(db)
        current_positions = await monitor.get_positions_snapshot(body.account_id)
    except Exception as e:
        logger.warning("[CapacityRouter] Failed to get position snapshot: %s", e)
        current_positions = {}

    # 获取待处理 ENTRY 信号
    try:
        stmt = (
            select(TradingSignal)
            .where(
                and_(
                    TradingSignal.account_id == body.account_id,
                    TradingSignal.status.in_(
                        [SignalStatus.GENERATED, SignalStatus.VALIDATED]
                    ),
                    TradingSignal.signal_type == SignalType.ENTRY,
                )
            )
            .order_by(TradingSignal.created_at.desc())
            .limit(20)
        )
        res = await db.execute(stmt)
        raw_signals = res.scalars().all()
        entry_signals = [
            {
                "id": s.id,
                "symbol": s.symbol,
                "signal_type": s.signal_type.value if s.signal_type else "ENTRY",
                "direction": s.direction or "LONG",
                "confidence": s.confidence or 0.0,
                "signal_strength": s.signal_strength or 0.0,
                "extra_metadata": s.extra_metadata or {},
                "factor_scores": s.factor_scores if hasattr(s, "factor_scores") else {},
            }
            for s in raw_signals
        ]
    except Exception as e:
        logger.warning("[CapacityRouter] Failed to get entry signals: %s", e)
        entry_signals = []

    # 执行 dry-run
    r_cfg = get_regime_adjusted_config(body.regime)
    max_positions = r_cfg.get("MAX_CONCURRENT_POSITIONS", 6)

    decision = await capacity_arbiter_service.evaluate(
        account_id=body.account_id,
        current_positions=current_positions,
        entry_signals=entry_signals,
        max_positions=max_positions,
        regime=body.regime,
        db=db,
        dry_run=True,
    )

    return CapacityPreviewResponse(
        cycle_id=decision.cycle_id,
        overflow=decision.overflow,
        max_positions=decision.max_positions,
        positions_count=decision.positions_count,
        signals_count=decision.signals_count,
        approved_signals=[
            {
                "signal_id": s.get("id"),
                "symbol": s.get("symbol", ""),
                "admission_score": s.get("signal_quality_score"),
            }
            for s in decision.approved_signals
        ],
        rejected_signals=[
            {"signal_id": s.get("id"), "symbol": s.get("symbol", "")}
            for s in decision.rejected_signals
        ],
        positions_to_close=decision.positions_to_close,
        candidates_snapshot=[
            CandidateSnapshot(**c)
            for c in decision.candidates_snapshot
            if isinstance(c, dict)
        ],
        min_edge_protected=decision.min_edge_protected,
        cooldown_protected=decision.cooldown_protected,
        min_hold_protected=decision.min_hold_protected,
        max_replacements_cap=decision.max_replacements_cap,
        replacement_triggered=decision.replacement_triggered,
        dry_run=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 日志列表 / 详情
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/logs", summary="仲裁决策日志列表", response_model=CapacityLogListResponse)
async def list_capacity_logs(
    account_id: Optional[str] = Query(None, description="账户 ID 过滤"),
    only_replacement: bool = Query(False, description="仅显示触发了替换的记录"),
    include_dry_run: bool = Query(True, description="是否包含 dry_run 记录"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    from app.models.capacity_decision_log import CapacityDecisionLog

    stmt = select(CapacityDecisionLog)
    conditions = []
    if account_id:
        conditions.append(CapacityDecisionLog.account_id == account_id)
    if only_replacement:
        conditions.append(CapacityDecisionLog.replacement_triggered.is_(True))
    if not include_dry_run:
        conditions.append(CapacityDecisionLog.dry_run.is_(False))
    if conditions:
        stmt = stmt.where(and_(*conditions))

    # count
    count_stmt = select(func.count()).select_from(CapacityDecisionLog)
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        stmt.order_by(desc(CapacityDecisionLog.created_at))
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        CapacityLogItem(
            id=r.id,
            account_id=r.account_id,
            cycle_id=r.cycle_id,
            regime=r.regime,
            trigger_reason=r.trigger_reason,
            max_positions=r.max_positions,
            positions_count=r.positions_count,
            signals_count=r.signals_count,
            overflow_count=r.overflow_count,
            min_edge_protected=r.min_edge_protected,
            cooldown_protected=r.cooldown_protected,
            min_hold_protected=r.min_hold_protected,
            max_replacements_cap=r.max_replacements_cap,
            dry_run=r.dry_run,
            replacement_triggered=r.replacement_triggered,
            created_at=r.created_at,
            eliminated_positions_count=len(r.eliminated_positions or []),
            eliminated_signals_count=len(r.eliminated_signals or []),
            approved_signals_count=len(r.approved_signals or []),
        )
        for r in rows
    ]

    return CapacityLogListResponse(total=total, page=page, size=size, items=items)


@router.get(
    "/logs/{log_id}",
    summary="单条仲裁日志详情",
    response_model=CapacityLogDetailResponse,
)
async def get_capacity_log_detail(
    log_id: int,
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    from app.models.capacity_decision_log import CapacityDecisionLog

    row = (
        (
            await db.execute(
                select(CapacityDecisionLog).where(CapacityDecisionLog.id == log_id)
            )
        )
        .scalars()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Capacity log {log_id} not found")

    snapshots = []
    for c in row.candidates_snapshot or []:
        if isinstance(c, dict):
            try:
                snapshots.append(CandidateSnapshot(**c))
            except Exception:
                pass

    return CapacityLogDetailResponse(
        id=row.id,
        account_id=row.account_id,
        cycle_id=row.cycle_id,
        regime=row.regime,
        trigger_reason=row.trigger_reason,
        max_positions=row.max_positions,
        positions_count=row.positions_count,
        signals_count=row.signals_count,
        overflow_count=row.overflow_count,
        min_edge_protected=row.min_edge_protected,
        cooldown_protected=row.cooldown_protected,
        min_hold_protected=row.min_hold_protected,
        max_replacements_cap=row.max_replacements_cap,
        dry_run=row.dry_run,
        replacement_triggered=row.replacement_triggered,
        created_at=row.created_at,
        eliminated_positions_count=len(row.eliminated_positions or []),
        eliminated_signals_count=len(row.eliminated_signals or []),
        approved_signals_count=len(row.approved_signals or []),
        candidates_snapshot=snapshots,
        eliminated_positions=row.eliminated_positions or [],
        eliminated_signals=row.eliminated_signals or [],
        approved_signals_detail=row.approved_signals or [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 仲裁统计摘要
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/stats", summary="席位竞争仲裁统计摘要", response_model=CapacityStatsResponse
)
async def get_capacity_stats(
    account_id: Optional[str] = Query(None),
    window_days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    from sqlalchemy import Float, case

    from app.models.capacity_decision_log import CapacityDecisionLog

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    cutoff_naive = cutoff.replace(tzinfo=None)

    conditions = [CapacityDecisionLog.created_at >= cutoff_naive]
    if account_id:
        conditions.append(CapacityDecisionLog.account_id == account_id)

    stmt = select(CapacityDecisionLog).where(and_(*conditions))
    rows = (await db.execute(stmt)).scalars().all()

    total = len(rows)
    if total == 0:
        return CapacityStatsResponse(window_days=window_days)

    replacements = sum(1 for r in rows if r.replacement_triggered)
    dry_runs = sum(1 for r in rows if r.dry_run)
    sig_rejected = sum(len(r.eliminated_signals or []) for r in rows)
    pos_closed = sum(len(r.eliminated_positions or []) for r in rows)
    min_edge_prot = sum(r.min_edge_protected for r in rows)
    cooldown_prot = sum(r.cooldown_protected for r in rows)
    avg_overflow = sum(r.overflow_count for r in rows) / total if total else 0.0

    # 每日席位利用趋势（简化：取每条记录的 positions_count / max_positions）
    trend_by_date: dict[str, list[float]] = {}
    for r in rows:
        day = r.created_at.strftime("%Y-%m-%d")
        util = (r.positions_count / r.max_positions) if r.max_positions else 0.0
        trend_by_date.setdefault(day, []).append(util)
    seat_utilization_trend = [
        {"date": d, "utilization": round(sum(v) / len(v), 3)}
        for d, v in sorted(trend_by_date.items())
    ]

    total_protections = min_edge_prot + cooldown_prot
    protection_total = total_protections or 1

    return CapacityStatsResponse(
        window_days=window_days,
        total_arbitrations=total,
        total_replacements=replacements,
        replacement_rate=round(replacements / total, 3) if total else 0.0,
        total_signals_rejected=sig_rejected,
        total_positions_closed=pos_closed,
        min_edge_protection_rate=round(min_edge_prot / protection_total, 3),
        cooldown_protection_rate=round(cooldown_prot / protection_total, 3),
        avg_overflow=round(avg_overflow, 2),
        dry_run_pct=round(dry_runs / total, 3) if total else 0.0,
        seat_utilization_trend=seat_utilization_trend,
    )
