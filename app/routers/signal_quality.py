"""V10.4.2: 信号精英化 API 路由

Endpoints:
  GET  /api/v1/signals/quality-config          → 查看当前漏斗参数
  PATCH /api/v1/signals/quality-config         → 热更新漏斗参数（需鉴权）
  GET  /api/v1/signals/audit-log               → 信号审计日志列表
  GET  /api/v1/signals/funnel-stats            → 漏斗统计数据
  GET  /api/v1/signals/ghost-trades            → 幽灵交易列表
  GET  /api/v1/signals/ghost-trades/analysis   → 幽灵胜率 vs 实际胜率分析
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.models.position import Position, PositionStatus
from app.models.trading_plan import TradingPlan
from app.models.trading_signal import (
    SignalSource,
    SignalStatus,
    SignalType,
    TradingSignal,
)
from app.services.ghost_trade_service import ghost_trade_service
from app.services.regime_classifier import RegimeClassifier
from app.services.signal_audit_log_service import signal_audit_log_service
from app.services.signal_quality_config import (
    apply_runtime_override,
    get_regime_adjusted_config,
    get_signal_quality_config,
    reset_runtime_overrides,
)

router = APIRouter(prefix="/api/v1/signals", tags=["Signal Quality (V10.4.2)"])


# ─────────────────────────────────────────────────────────────────────────────
# 漏斗配置
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/quality-config", summary="查看信号精英化漏斗参数")
async def get_quality_config(
    _user: str = Depends(get_current_user),
):
    """返回当前信号品质漏斗的所有可配置参数（含运行时覆盖值）。"""
    cfg = get_signal_quality_config()
    return {
        "elite_signal_score": cfg.ELITE_SIGNAL_SCORE,
        "elite_signal_floor": cfg.ELITE_SIGNAL_FLOOR,
        "elite_min_aligned_dims": cfg.ELITE_MIN_ALIGNED_DIMS,
        "high_quality_signal_score": cfg.HIGH_QUALITY_SIGNAL_SCORE,
        "medium_quality_signal_score": cfg.MEDIUM_QUALITY_SIGNAL_SCORE,
        "signal_confidence_threshold": cfg.SIGNAL_CONFIDENCE_THRESHOLD,
        "signal_resonance_min_dims": cfg.SIGNAL_RESONANCE_MIN_DIMS,
        "max_concurrent_positions": cfg.MAX_CONCURRENT_POSITIONS,
        "max_daily_signals": cfg.MAX_DAILY_SIGNALS,
        "max_position_correlation": cfg.MAX_POSITION_CORRELATION,
        "min_adv_threshold": cfg.MIN_ADV_THRESHOLD,
        "min_market_cap": cfg.MIN_MARKET_CAP,
        "ghost_trade_max_days": cfg.GHOST_TRADE_MAX_DAYS,
        "min_calibrated_floor": cfg.SIGNAL_CONFIDENCE_FLOOR,
        "min_expected_sharpe": cfg.MIN_EXPECTED_SHARPE,
    }


@router.patch("/quality-config", summary="热更新信号漏斗参数（运行时生效，重启后重置）")
async def patch_quality_config(
    body: dict,
    _user: str = Depends(get_current_user),
):
    """
    运行时热更新漏斗参数，重启后恢复默认值。

    可调字段（传入 JSON 对象，只需包含要修改的 key）：
    - signal_confidence_threshold (int, 50-100)
    - signal_resonance_min_dims   (int, 1-6)
    - max_concurrent_positions    (int, 1-20)
    - max_daily_signals           (int, 1-20)
    - max_position_correlation    (float, 0-1)
    """
    # key 映射：前端小写下划线 → 内部大写常量
    _KEY_MAP = {
        "elite_signal_score": "ELITE_SIGNAL_SCORE",
        "elite_signal_floor": "ELITE_SIGNAL_FLOOR",
        "elite_min_aligned_dims": "ELITE_MIN_ALIGNED_DIMS",
        "high_quality_signal_score": "HIGH_QUALITY_SIGNAL_SCORE",
        "medium_quality_signal_score": "MEDIUM_QUALITY_SIGNAL_SCORE",
        "signal_confidence_threshold": "SIGNAL_CONFIDENCE_THRESHOLD",
        "signal_resonance_min_dims": "SIGNAL_RESONANCE_MIN_DIMS",
        "max_concurrent_positions": "MAX_CONCURRENT_POSITIONS",
        "max_daily_signals": "MAX_DAILY_SIGNALS",
        "max_position_correlation": "MAX_POSITION_CORRELATION",
    }
    overrides: dict = {}
    for k, v in body.items():
        mapped = _KEY_MAP.get(k)
        if mapped:
            overrides[mapped] = v

    if not overrides:
        return {"updated": False, "message": "无有效参数"}

    apply_runtime_override(overrides)
    cfg = get_signal_quality_config()
    return {
        "updated": True,
        "applied": overrides,
        "current": {
            "elite_signal_score": cfg.ELITE_SIGNAL_SCORE,
            "elite_signal_floor": cfg.ELITE_SIGNAL_FLOOR,
            "elite_min_aligned_dims": cfg.ELITE_MIN_ALIGNED_DIMS,
            "high_quality_signal_score": cfg.HIGH_QUALITY_SIGNAL_SCORE,
            "medium_quality_signal_score": cfg.MEDIUM_QUALITY_SIGNAL_SCORE,
            "signal_confidence_threshold": cfg.SIGNAL_CONFIDENCE_THRESHOLD,
            "signal_resonance_min_dims": cfg.SIGNAL_RESONANCE_MIN_DIMS,
            "max_concurrent_positions": cfg.MAX_CONCURRENT_POSITIONS,
            "max_daily_signals": cfg.MAX_DAILY_SIGNALS,
            "max_position_correlation": cfg.MAX_POSITION_CORRELATION,
        },
    }


@router.delete("/quality-config/overrides", summary="重置运行时覆盖，恢复默认参数")
async def reset_quality_config(
    _user: str = Depends(get_current_user),
):
    """清除所有通过 PATCH 接口修改的运行时参数，恢复到环境变量默认值。"""
    reset_runtime_overrides()
    return {"reset": True, "message": "已恢复默认参数"}


# ─────────────────────────────────────────────────────────────────────────────
# 审计日志
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/audit-log", summary="信号品质审计日志列表")
async def get_audit_log(
    limit: int = Query(50, ge=1, le=200, description="每页条数"),
    offset: int = Query(0, ge=0),
    funnel_result: Optional[str] = Query(None, description="PASSED / REJECTED"),
    symbol: Optional[str] = Query(None),
    since_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    """
    返回近 `since_days` 天内经过漏斗评估的信号列表，
    可按 symbol / funnel_result 过滤。
    """
    rows = await signal_audit_log_service.get_recent(
        db,
        limit=limit,
        offset=offset,
        funnel_result=funnel_result,
        symbol=symbol,
        since_days=since_days,
    )
    return {"data": rows, "offset": offset, "limit": limit, "count": len(rows)}


# ─────────────────────────────────────────────────────────────────────────────
# 漏斗统计
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/funnel-stats", summary="漏斗统计数据（精英率、逐层拒绝量、趋势）")
async def get_funnel_stats(
    since_days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    """
    Returns:
    - total_evaluated: 总评估信号数
    - total_passed: 通过精英漏斗的信号数
    - elite_rate_pct: 精英化率 (%)
    - layer_stats: 每层被拒数量
    - rejection_breakdown: 按拒绝原因统计
    - daily_trend: 近 N 天每日精英率趋势
    - current_positions_count: 当前 HELD 持仓数量
    - max_concurrent_positions_cfg: 基础配置的最大并发仓位
    - effective_max_concurrent_positions: 当前体制下生效的最大并发仓位
    - current_regime: 当前体制
    - regime_confidence: 当前体制置信度
    - capacity_guard: 最近容量守卫自动减仓动作摘要
    """
    stats = await signal_audit_log_service.get_funnel_stats(db, since_days=since_days)

    # 实时注入当前持仓数与配置上限，帮助解释 L2 (MAX_POSITIONS_REACHED) 拦截原因
    # V10.4.4+: 查 positions 表（ACTIVE/SCALING_IN/SCALING_OUT/PARTIALLY_CLOSED 均为实际持仓）
    _held_statuses = [
        PositionStatus.ACTIVE.value,
        PositionStatus.SCALING_IN.value,
        PositionStatus.SCALING_OUT.value,
        PositionStatus.PARTIALLY_CLOSED.value,
    ]
    held_count_stmt = (
        select(func.count())
        .select_from(Position)
        .where(Position.status.in_(_held_statuses))
    )
    current_positions_count = (
        await db.execute(held_count_stmt)
    ).scalar_one_or_none() or 0

    cfg = get_signal_quality_config()
    current_regime = await RegimeClassifier.get_current_regime(db)
    regime_name = current_regime.regime if current_regime else None
    effective_cfg = get_regime_adjusted_config(regime_name) if regime_name else {}

    stats["current_positions_count"] = current_positions_count
    stats["max_concurrent_positions_cfg"] = cfg.MAX_CONCURRENT_POSITIONS
    stats["effective_max_concurrent_positions"] = int(
        effective_cfg.get("MAX_CONCURRENT_POSITIONS", cfg.MAX_CONCURRENT_POSITIONS)
    )
    stats["current_regime"] = regime_name
    stats["regime_confidence"] = current_regime.confidence if current_regime else None

    guard_cutoff = datetime.now(timezone.utc) - timedelta(days=max(since_days, 7))
    capacity_stmt = (
        select(TradingSignal)
        .where(
            and_(
                TradingSignal.signal_source == SignalSource.RISK_MGMT,
                TradingSignal.signal_type == SignalType.EXIT,
                TradingSignal.created_at >= guard_cutoff,
            )
        )
        .order_by(desc(TradingSignal.created_at))
        .limit(50)
    )
    capacity_rows = (await db.execute(capacity_stmt)).scalars().all()

    capacity_actions = []
    for row in capacity_rows:
        meta = row.extra_metadata or {}
        if not isinstance(meta, dict) or not meta.get("capacity_guard"):
            continue
        capacity_actions.append(
            {
                "signal_id": row.signal_id,
                "symbol": row.symbol,
                "status": (
                    row.status.value
                    if hasattr(row.status, "value")
                    else str(row.status)
                ),
                "quantity": row.suggested_quantity,
                "priority": row.priority,
                "recommendation": meta.get("recommendation"),
                "risk_level": meta.get("risk_level"),
                "target_position": meta.get("target_position"),
                "overflow": meta.get("capacity_guard_overflow"),
                "target_max": meta.get("capacity_guard_target_max"),
                "rank": meta.get("capacity_guard_rank"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "executed_at": row.executed_at.isoformat() if row.executed_at else None,
                "notes": row.notes,
            }
        )

    open_statuses = {
        SignalStatus.GENERATED.value,
        SignalStatus.VALIDATED.value,
        SignalStatus.QUEUED.value,
        SignalStatus.EXECUTING.value,
    }
    stats["capacity_guard"] = {
        "recent_generated_count": len(capacity_actions),
        "open_signal_count": sum(
            1 for item in capacity_actions if item["status"] in open_statuses
        ),
        "last_action_at": (
            capacity_actions[0]["created_at"] if capacity_actions else None
        ),
        "recent_actions": capacity_actions[:8],
    }

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# 幽灵交易
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/ghost-trades", summary="幽灵交易列表（被拒信号的虚拟跟踪）")
async def get_ghost_trades(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ghost_result: Optional[str] = Query(
        None, description="WIN / LOSS / OPEN / EXPIRED"
    ),
    symbol: Optional[str] = Query(None),
    since_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    """返回被漏斗拒绝信号的虚拟仓位跟踪，用于事后反事实验证。"""
    rows = await ghost_trade_service.get_ghost_trades(
        db,
        limit=limit,
        offset=offset,
        ghost_result=ghost_result,
        symbol=symbol,
        since_days=since_days,
    )
    return {"data": rows, "offset": offset, "limit": limit, "count": len(rows)}


@router.get("/ghost-trades/analysis", summary="幽灵胜率 vs 实际胜率对比分析")
async def get_ghost_analysis(
    since_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
):
    """
    对比幽灵交易胜率与实际信号胜率，评估漏斗是否过严/过松。

    返回字段包括：
    - ghost_win_rate_pct: 幽灵交易胜率
    - real_win_rate_pct:  实际信号胜率（不足时为 null）
    - win_rate_gap_pct:   差距（正值=漏斗过严，负值=漏斗有效）
    - layer_breakdown:    按拒绝层的胜率分布
    - reason_breakdown:   按拒绝原因的胜率分布
    - recommendation:     LOOSEN_THRESHOLD / MAINTAIN / TIGHTEN_THRESHOLD
    - conclusion:         可读性诊断结论
    """
    return await ghost_trade_service.get_ghost_analysis(db, since_days=since_days)
