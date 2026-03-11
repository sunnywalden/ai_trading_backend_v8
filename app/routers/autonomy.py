"""V10: AI 自主控制路由"""
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select, func, and_, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.broker.factory import make_option_broker_client
from app.models.trading_plan import TradingPlan
from app.core.runtime_config import (
    get_autonomy_level,
    set_autonomy_level,
    clear_autonomy_level_override,
)
from app.models.db import get_session
from app.models.trading_signal import TradingSignal, SignalStatus
from app.models.autonomy_audit_log import AutonomyAuditLog
from app.models.strategy import Strategy, StrategyRun, HistoricalStrategyRun
from app.services.autonomous_engine import autonomous_engine
from app.services.portfolio_cache_service import invalidate_portfolio_view_caches
from app.services.signal_quality_funnel import signal_quality_funnel, SignalQualityTier

router = APIRouter(prefix="/autonomy", tags=["V10-Autonomy"])

_ACCOUNT_ID_CACHE_TTL_SECONDS = 300
_cached_account_id: Optional[str] = None
_cached_account_expires_at: Optional[datetime] = None


class AutonomyLevelUpdate(BaseModel):
    level: str  # FULL / SEMI / ADVISORY


class RevokeRequest(BaseModel):
    reason: str = "手动撤销"


async def _resolve_account_id() -> str:
    """优先解析 Tiger 实际账户号，避免 settings.TIGER_ACCOUNT 与真实账户不一致。"""
    global _cached_account_id, _cached_account_expires_at
    now = datetime.now(timezone.utc)
    if _cached_account_id and _cached_account_expires_at and _cached_account_expires_at > now:
        return _cached_account_id
    try:
        broker = make_option_broker_client()
        real_acc = await asyncio.wait_for(broker.get_account_id(), timeout=2.0)
        if real_acc:
            _cached_account_id = str(real_acc)
            _cached_account_expires_at = now + timedelta(seconds=_ACCOUNT_ID_CACHE_TTL_SECONDS)
            return _cached_account_id
    except Exception:
        pass
    _cached_account_id = str(settings.TIGER_ACCOUNT or "")
    _cached_account_expires_at = now + timedelta(seconds=_ACCOUNT_ID_CACHE_TTL_SECONDS)
    return _cached_account_id


def _coerce_dt(value) -> Optional[datetime]:
    """尽力将 Tiger 订单时间字段转换为 timezone-aware UTC datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # 兼容秒/毫秒时间戳
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            # 兼容 ISO 8601（含 Z）
            s2 = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s2)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _get_order_dt(order) -> Optional[datetime]:
    """从 Tiger 订单对象上提取最可能的成交/更新时间。"""
    for attr in (
        "trade_time",
        "filled_time",
        "updated_at",
        "update_time",
        "created_at",
        "create_time",
        "order_time",
        "time",
    ):
        dt = _coerce_dt(getattr(order, attr, None))
        if dt is not None:
            return dt.astimezone(timezone.utc)
    return None


def _get_order_status(order) -> str:
    raw = getattr(order, "status", None)
    if raw is None:
        return ""
    if hasattr(raw, "name"):
        return str(raw.name).upper()
    s = str(raw).upper()
    if "." in s:
        s = s.split(".")[-1]
    return s


def _build_signal_quality_snapshot(signal: TradingSignal) -> dict[str, object]:
    signal_type = signal.signal_type.value if signal.signal_type else "ENTRY"
    extra_meta: dict[str, Any] = signal.extra_metadata if isinstance(signal.extra_metadata, dict) else {}
    factor_scores: dict[str, Any] = signal.factor_scores if isinstance(signal.factor_scores, dict) else {}
    _raw_signal_payload = extra_meta.get("signal_payload")
    signal_payload: dict[str, Any] = _raw_signal_payload if isinstance(_raw_signal_payload, dict) else {}
    _raw_payload_dims = signal_payload.get("dimensions")
    payload_dims: dict[str, Any] = _raw_payload_dims if isinstance(_raw_payload_dims, dict) else {}
    _raw_payload_quality = signal_payload.get("quality_inputs")
    payload_quality: dict[str, Any] = _raw_payload_quality if isinstance(_raw_payload_quality, dict) else {}
    if signal_type in ("EXIT", "REDUCE") or bool(extra_meta.get("force_exit")):
        return {
            "signal_quality_tier": None,
            "signal_quality_score": None,
            "signal_quality_quota_exempt": False,
        }

    def _as_list(value: Any) -> list[Any]:
        return list(value) if isinstance(value, list) else []

    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    dimensions = _as_list(
        payload_dims.get("dimensions") or extra_meta.get("dimensions") or factor_scores.get("dimensions") or []
    )

    def _dim_dir(name: str) -> int:
        for item in dimensions:
            if isinstance(item, dict) and item.get("name") == name:
                try:
                    return int(item.get("direction", 0))
                except Exception:
                    return 0
        return 0

    def _dim_score(name: str) -> float:
        for item in dimensions:
            if isinstance(item, dict) and item.get("name") == name:
                try:
                    score = float(item.get("score", 0.5))
                except Exception:
                    score = 0.5
                return score / 100.0 if score > 1.0 else score
        raw = extra_meta.get(f"{name}_score")
        if raw is None:
            raw = payload_dims.get(f"{name}_score")
        if raw is None:
            raw = factor_scores.get(f"{name}_score")
        if raw is None:
            return 0.5
        try:
            score = float(raw)
        except Exception:
            return 0.5
        return score / 100.0 if score > 1.0 else score

    from app.services.signal_quality_funnel import SignalFunnelInput

    profile = signal_quality_funnel.preview_quality(
        SignalFunnelInput(
            signal_id=signal.id,
            signal_type=signal_type,
            signal_strength=float(signal.signal_strength or 0.0),
            symbol=signal.symbol,
            direction=str(signal.direction or "LONG").upper(),
            regime=str(extra_meta.get("regime") or "SIDEWAYS"),
            composite_score=float(signal.confidence or 0.0),
            aligned_count=int(payload_dims.get("aligned_count") or payload_quality.get("aligned_count") or extra_meta.get("aligned_count") or factor_scores.get("aligned_count") or 0),
            aligned_dims=_as_list(payload_dims.get("aligned_dims") or extra_meta.get("aligned_dims") or factor_scores.get("aligned_dims") or []),
            opposing_dims=_as_list(payload_dims.get("opposing_dims") or extra_meta.get("opposing_dims") or factor_scores.get("opposing_dims") or []),
            neutral_dims=_as_list(payload_dims.get("neutral_dims") or extra_meta.get("neutral_dims") or factor_scores.get("neutral_dims") or []),
            tech_direction=_dim_dir("technical"),
            fundamental_direction=_dim_dir("fundamental"),
            macro_score=_dim_score("macro"),
            options_score=_dim_score("options"),
            adv_usd=_as_float(payload_dims.get("adv_usd") or extra_meta.get("adv_usd") or factor_scores.get("adv_usd")),
            market_cap=_as_float(payload_dims.get("market_cap") or extra_meta.get("market_cap") or factor_scores.get("market_cap")),
            historical_ic=_as_float(payload_quality.get("historical_ic") or payload_dims.get("historical_ic") or extra_meta.get("historical_ic") or factor_scores.get("historical_ic")),
            timing_quality=_as_float(payload_quality.get("timing_quality") or payload_dims.get("timing_quality") or extra_meta.get("timing_quality") or factor_scores.get("timing_quality")),
        )
    )
    return {
        "signal_quality_tier": profile.tier,
        "signal_quality_score": profile.score,
        "signal_quality_quota_exempt": profile.quota_exempt,
    }


async def _count_broker_filled_today(account_id: str) -> Optional[int]:
    """统计券商侧“今日已成交”订单笔数（用于展示口径对齐）。"""
    try:
        broker = make_option_broker_client()
        trade_client = getattr(broker, "trade_client", None)
        if trade_client is None:
            return None

        def _fetch_orders():
            try:
                return trade_client.get_orders(account=account_id, limit=500)
            except TypeError:
                return trade_client.get_orders(account=account_id)

        orders = await asyncio.wait_for(asyncio.to_thread(_fetch_orders), timeout=3.0)
        if not orders:
            return 0

        today_utc = datetime.now(timezone.utc).date()
        filled = 0
        for o in orders:
            status = _get_order_status(o)
            if status != "FILLED":
                continue
            odt = _get_order_dt(o)
            if odt is None:
                continue
            if odt.date() == today_utc:
                filled += 1
        return filled
    except Exception:
        return None


@router.get("/status")
async def get_autonomy_status(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取 AI 自主运行状态 (V10)，包含实时信号流水线统计"""
    account_id = await _resolve_account_id()
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc_date = today.date().isoformat()

    # 今日已执行交易数（与引擎对齐：从审计日志统计 order_id 非空的下单记录）
    exec_result = await session.execute(
        select(func.count(AutonomyAuditLog.id)).where(
            and_(
                AutonomyAuditLog.account_id == account_id,
                AutonomyAuditLog.order_id.isnot(None),
                AutonomyAuditLog.created_at >= today,
            )
        )
    )
    daily_trades = exec_result.scalar() or 0
    broker_filled_today = await _count_broker_filled_today(account_id)

    # 信号流水线各状态数量（今日）
    pipeline_result = await session.execute(
        select(TradingSignal.status, func.count(TradingSignal.id))
        .where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.created_at >= today - timedelta(days=1),
            )
        )
        .group_by(TradingSignal.status)
    )
    pipeline = {row[0].value: row[1] for row in pipeline_result.fetchall()}

    today_signal_rows = await session.execute(
        select(TradingSignal)
        .where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.created_at >= today,
            )
        )
    )
    today_signals = today_signal_rows.scalars().all()
    closing_signals = [
        s for s in today_signals
        if s.signal_type.value in ("EXIT", "REDUCE")
        or (isinstance(s.extra_metadata, dict) and bool(s.extra_metadata.get("force_exit")))
    ]
    force_exit_signals = [
        s for s in closing_signals
        if isinstance(s.extra_metadata, dict) and bool(s.extra_metadata.get("force_exit"))
    ]
    closing_failed = [
        s for s in closing_signals
        if s.status in {SignalStatus.REJECTED, SignalStatus.FAILED}
    ]
    quality_snapshots: list[dict[str, object]] = []
    elite_count = 0
    high_quality_count = 0
    quota_exempt_count = 0
    pending_elite_count = 0
    for signal in today_signals:
        snapshot = _build_signal_quality_snapshot(signal)
        quality_snapshots.append(snapshot)
        tier = snapshot.get("signal_quality_tier")
        if tier == SignalQualityTier.ELITE:
            elite_count += 1
            if signal.status in {SignalStatus.GENERATED, SignalStatus.VALIDATED, SignalStatus.QUEUED}:
                pending_elite_count += 1
        if tier in {SignalQualityTier.ELITE, SignalQualityTier.HIGH}:
            high_quality_count += 1
        if bool(snapshot.get("signal_quality_quota_exempt")):
            quota_exempt_count += 1

    # 熔断：若今日已执行失败超过 3 笔，视为熔断触发
    fail_result = await session.execute(
        select(func.count(TradingSignal.id)).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.status == SignalStatus.FAILED,
                TradingSignal.created_at >= today,
            )
        )
    )
    failed_today = fail_result.scalar() or 0

    # 活跃冷却标的：查询过去 cooldown_min 分钟内由 AI_AUTONOMOUS 成交的计划
    cooldown_min = int(getattr(settings, "AUTONOMOUS_ORDER_COOLDOWN_MINUTES", 120) or 120)
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_min)
    cooldown_result = await session.execute(
        select(
            TradingPlan.symbol,
            TradingPlan.direction,
            TradingPlan.created_at,
        )
        .where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.source == "AI_AUTONOMOUS",
                TradingPlan.created_at >= cooldown_cutoff,
                TradingPlan.plan_status.in_(["EXECUTED", "ACTIVE"]),
            )
        )
        .order_by(TradingPlan.created_at.desc())
    )
    cooldown_rows = cooldown_result.fetchall()
    cooldown_symbols = []
    for row in cooldown_rows:
        executed_at = row.created_at
        if executed_at and executed_at.tzinfo is None:
            executed_at = executed_at.replace(tzinfo=timezone.utc)
        expires_at = executed_at + timedelta(minutes=cooldown_min) if executed_at else None
        remaining_min = (
            int((expires_at - datetime.now(timezone.utc)).total_seconds() / 60)
            if expires_at and expires_at > datetime.now(timezone.utc)
            else 0
        )
        cooldown_symbols.append({
            "symbol": row.symbol,
            "direction": row.direction,
            "executed_at": executed_at.isoformat() if executed_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "remaining_minutes": max(0, remaining_min),
        })

    return {
        "level": await get_autonomy_level(),
        "paused": not autonomous_engine.is_running,
        "circuit_breaker_triggered": failed_today >= 3,
        "daily_trades_today": daily_trades,
        "daily_trades_today_autonomous": daily_trades,
        "daily_trades_today_broker": broker_filled_today,
        "daily_trades_today_broker_tz": "UTC",
        "daily_trades_today_broker_date": today_utc_date,
        "max_daily_trades": settings.MAX_DAILY_TRADES,
        "revoke_window_minutes": settings.REVOKE_WINDOW_MINUTES,
        "signal_pipeline": pipeline,
        "failed_trades_today": failed_today,
        "cooldown_symbols": cooldown_symbols,
        "cooldown_minutes": cooldown_min,
        "closing_flow": {
            "closing_signals_today": len(closing_signals),
            "fast_path_signals_today": len(closing_signals),
            "force_exit_signals_today": len(force_exit_signals),
            "closing_failures_today": len(closing_failed),
        },
        "signal_quality": {
            "elite_signals_today": elite_count,
            "high_quality_signals_today": high_quality_count,
            "pending_elite_signals": pending_elite_count,
            "quota_exempt_signals_today": quota_exempt_count,
        },
    }


@router.put("/level")
async def update_autonomy_level(
    body: AutonomyLevelUpdate,
    current_user: str = Depends(get_current_user),
):
    """切换 AI 自主级别（立即生效）"""
    valid = {"FULL", "SEMI", "ADVISORY"}
    if body.level not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid level. Must be one of: {valid}")
    # 写入 Redis 持久化 + 更新进程内值；重启后仍生效
    await set_autonomy_level(body.level)
    return {"success": True, "autonomy_level": body.level}


@router.post("/pause")
async def pause_autonomy(current_user: str = Depends(get_current_user)):
    """紧急暂停 AI (V10)"""
    autonomous_engine.pause()
    return {"success": True, "message": "AI 自主决策循环已停止"}


@router.post("/resume")
async def resume_autonomy(current_user: str = Depends(get_current_user)):
    """恢复 AI (V10)"""
    autonomous_engine.resume()
    return {"success": True, "message": "AI 自主决策循环已恢复"}


@router.get("/audit-log")
async def get_audit_log(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取 AI 自主决策审计日志"""
    safe_limit = max(1, min(int(limit or 20), 200))
    safe_offset = max(0, int(offset or 0))

    # 总数（用于前端分页）
    total_res = await session.execute(select(func.count(AutonomyAuditLog.id)))
    total = int(total_res.scalar() or 0)

    result = await session.execute(
        select(AutonomyAuditLog)
        .order_by(AutonomyAuditLog.created_at.desc())
        .offset(safe_offset)
        .limit(safe_limit)
    )
    rows = result.scalars().all()

    # 通过 order_id 回填数量语义（若可关联到 trading_signals）
    order_ids = [str(r.order_id) for r in rows if getattr(r, "order_id", None)]
    signal_map: dict[str, TradingSignal] = {}
    if order_ids:
        sig_result = await session.execute(
            select(TradingSignal)
            .where(TradingSignal.order_id.in_(order_ids))
            .order_by(TradingSignal.created_at.desc())
        )
        for sig in sig_result.scalars().all():
            oid = str(getattr(sig, "order_id", "") or "")
            if oid and oid not in signal_map:
                signal_map[oid] = sig

    return {
        "logs": [
            {
                "id": r.id,
                "autonomy_level": r.autonomy_level,
                "decision_type": r.decision_type,
                "symbol": r.symbol,
                "direction": r.decision_type if r.decision_type in ("BUY", "SELL") else None,
                "confidence_score": float(r.confidence_score) if r.confidence_score is not None else None,
                "risk_gate_passed": bool(r.risk_gate_passed),
                "order_id": r.order_id,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                "circuit_breaker": bool(r.circuit_breaker_triggered),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "ai_reasoning": r.ai_reasoning,
                "quantity": (
                    signal_map[str(r.order_id)].quantity_value
                    if r.order_id and str(r.order_id) in signal_map and signal_map[str(r.order_id)].quantity_value is not None
                    else (
                        signal_map[str(r.order_id)].suggested_quantity
                        if r.order_id and str(r.order_id) in signal_map
                        else None
                    )
                ),
                "quantity_mode": (
                    signal_map[str(r.order_id)].quantity_mode
                    if r.order_id and str(r.order_id) in signal_map
                    else None
                ),
                "quantity_value": (
                    signal_map[str(r.order_id)].quantity_value
                    if r.order_id and str(r.order_id) in signal_map
                    else None
                ),
                "execution_path": (
                    ((r.risk_gate_detail or {}).get("execution_path"))
                    or (((signal_map[str(r.order_id)].extra_metadata if r.order_id and str(r.order_id) in signal_map else {}) or {}).get("execution_path"))
                    or "STANDARD"
                ),
                "closing_intent": bool(
                    ((r.risk_gate_detail or {}).get("closing_intent"))
                    or (((signal_map[str(r.order_id)].extra_metadata if r.order_id and str(r.order_id) in signal_map else {}) or {}).get("closing_intent"))
                ),
                "force_exit": bool(
                    ((r.risk_gate_detail or {}).get("force_exit"))
                    or (((signal_map[str(r.order_id)].extra_metadata if r.order_id and str(r.order_id) in signal_map else {}) or {}).get("force_exit"))
                ),
                "bypass_reason": (
                    (r.risk_gate_detail or {}).get("bypass_reason")
                    or (((signal_map[str(r.order_id)].extra_metadata if r.order_id and str(r.order_id) in signal_map else {}) or {}).get("bypass_reason"))
                ),
                "risk_gate_detail": r.risk_gate_detail,
                "circuit_breaker_triggered": bool(r.circuit_breaker_triggered),
                "signal_quality_tier": (
                    _build_signal_quality_snapshot(signal_map[str(r.order_id)])["signal_quality_tier"]
                    if r.order_id and str(r.order_id) in signal_map
                    else None
                ),
                "signal_quality_score": (
                    _build_signal_quality_snapshot(signal_map[str(r.order_id)])["signal_quality_score"]
                    if r.order_id and str(r.order_id) in signal_map
                    else None
                ),
                "signal_quality_quota_exempt": bool(
                    _build_signal_quality_snapshot(signal_map[str(r.order_id)])["signal_quality_quota_exempt"]
                    if r.order_id and str(r.order_id) in signal_map
                    else False
                ),
            }
            for r in rows
        ],
        "total": total,
    }


@router.post("/revoke/{exec_id}")
async def revoke_order(
    exec_id: str = Path(..., description="审计日志中的 order_id"),
    body: Optional[RevokeRequest] = None,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """在 30 分钟窗口内撤销 AI 自动执行的订单"""
    reason = body.reason if body else "手动撤销"
    result = await autonomous_engine.revoke_order("default", exec_id, reason, session)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return result


@router.get("/signal-pipeline")
async def get_signal_pipeline(
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """查看近期信号流水线：展示信号从生成到执行的完整状态链"""
    account_id = await _resolve_account_id()
    result = await session.execute(
        select(TradingSignal)
        .where(TradingSignal.account_id == account_id)
        .order_by(TradingSignal.created_at.desc())
        .limit(limit)
    )
    signals = result.scalars().all()

    strategy_ids = {s.strategy_id for s in signals if s.strategy_id}
    strategy_run_ids = {s.strategy_run_id for s in signals if s.strategy_run_id}

    strategy_name_map: dict[str, str] = {}
    strategy_run_map: dict[str, StrategyRun] = {}
    run_universe_meta_map: dict[str, dict] = {}

    if strategy_ids:
        strategy_result = await session.execute(
            select(Strategy.id, Strategy.name).where(Strategy.id.in_(strategy_ids))
        )
        strategy_name_map = {sid: sname for sid, sname in strategy_result.fetchall()}

    if strategy_run_ids:
        run_result = await session.execute(
            select(StrategyRun).where(StrategyRun.id.in_(strategy_run_ids))
        )
        strategy_run_map = {run.id: run for run in run_result.scalars().all()}

        history_result = await session.execute(
            select(HistoricalStrategyRun.strategy_run_id, HistoricalStrategyRun.status_payload)
            .where(HistoricalStrategyRun.strategy_run_id.in_(strategy_run_ids))
        )
        for run_id, status_payload in history_result.fetchall():
            universe_meta = {}
            if isinstance(status_payload, dict):
                universe_raw = status_payload.get("universe")
                if isinstance(universe_raw, dict):
                    universe_meta = universe_raw
            run_universe_meta_map[run_id] = universe_meta

    # 获取这些信号对应的执行意图（用于备注显示拒绝原因）
    from app.models.execution_intent import AutonomousExecutionIntent
    intent_map = {}
    if signals:
        signal_ids = [s.signal_id for s in signals]
        intent_result = await session.execute(
            select(AutonomousExecutionIntent.signal_id, AutonomousExecutionIntent.reason)
            .where(AutonomousExecutionIntent.signal_id.in_(signal_ids))
        )
        for sid, reason in intent_result:
            if sid and reason:
                intent_map[sid] = reason

    # 获取每个信号最新的漏斗审计结果（用于在流水线中显示漏斗拒绝原因，消除歧义）
    from app.models.signal_quality_audit_log import SignalQualityAuditLog
    funnel_map: dict = {}
    if signals:
        signal_ids_int = [s.id for s in signals if s.id is not None]
        if signal_ids_int:
            latest_subq = (
                select(
                    SignalQualityAuditLog.signal_id,
                    func.max(SignalQualityAuditLog.id).label("max_id"),
                )
                .where(SignalQualityAuditLog.signal_id.in_(signal_ids_int))
                .group_by(SignalQualityAuditLog.signal_id)
                .subquery()
            )
            funnel_rows = await session.execute(
                select(
                    SignalQualityAuditLog.signal_id,
                    SignalQualityAuditLog.funnel_result,
                    SignalQualityAuditLog.rejected_at_layer,
                    SignalQualityAuditLog.rejection_reason,
                    SignalQualityAuditLog.rejection_detail,
                ).join(latest_subq, SignalQualityAuditLog.id == latest_subq.c.max_id)
            )
            for sid, fresult, layer, reason, detail in funnel_rows:
                if sid is not None:
                    funnel_map[int(sid)] = {
                        "funnel_result": fresult,
                        "funnel_rejected_at_layer": layer,
                        "funnel_rejection_reason": reason,
                        "funnel_rejection_detail": detail,
                    }

    return {
        "signals": [
            {
                "signal_id": s.signal_id,
                "symbol": s.symbol,
                "type": s.signal_type.value,
                "source": s.signal_source.value,
                "status": s.status.value,
                "direction": s.direction,
                "quantity": s.suggested_quantity,
                "quantity_mode": s.quantity_mode,
                "quantity_value": s.quantity_value,
                "strength": round(s.confidence, 4) if s.confidence is not None else 0.0,  # 修复置信度显示：保留4位精度(前端*100后含2位小数)
                "priority": s.priority,
                "notes": (
                    intent_map.get(s.signal_id)
                    or s.notes
                    or (
                        (s.extra_metadata or {}).get("watchtower_reason_detail")
                        if isinstance(s.extra_metadata, dict)
                        else None
                    )
                    or (
                        (s.extra_metadata or {}).get("funnel_rejection_detail")
                        if isinstance(s.extra_metadata, dict)
                        else None
                    )
                    or funnel_map.get(s.id, {}).get("funnel_rejection_detail")
                ),
                "order_id": s.order_id,
                "execution_path": (
                    (s.extra_metadata or {}).get("execution_path")
                    if isinstance(s.extra_metadata, dict)
                    else "STANDARD"
                ) or "STANDARD",
                "closing_intent": bool(
                    s.signal_type.value in ("EXIT", "REDUCE")
                    or (isinstance(s.extra_metadata, dict) and (s.extra_metadata or {}).get("closing_intent"))
                ),
                "force_exit": bool(
                    isinstance(s.extra_metadata, dict) and (s.extra_metadata or {}).get("force_exit")
                ),
                "bypass_reason": (
                    (s.extra_metadata or {}).get("bypass_reason")
                    if isinstance(s.extra_metadata, dict)
                    else None
                ) or intent_map.get(s.signal_id),
                "strategy_id": s.strategy_id,
                "strategy_run_id": s.strategy_run_id,
                "strategy_name": (
                    (s.extra_metadata or {}).get("strategy_name")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or (strategy_name_map.get(s.strategy_id) if s.strategy_id else None)
                or (
                    strategy_run_map[s.strategy_run_id].strategy.name
                    if s.strategy_run_id in strategy_run_map and strategy_run_map[s.strategy_run_id].strategy
                    else None
                ),
                "strategy_version": (
                    (s.extra_metadata or {}).get("strategy_version")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or (
                    strategy_run_map[s.strategy_run_id].strategy_version
                    if s.strategy_run_id in strategy_run_map
                    else None
                ),
                "target_universe": (
                    (s.extra_metadata or {}).get("run_universe")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or (
                    strategy_run_map[s.strategy_run_id].target_universe
                    if s.strategy_run_id in strategy_run_map
                    else None
                ),
                "resolved_market": (
                    (s.extra_metadata or {}).get("resolved_market")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or (
                    (run_universe_meta_map.get(s.strategy_run_id) or {}).get("resolved_market")
                    if s.strategy_run_id
                    else None
                ),
                "selection_mode": (
                    (s.extra_metadata or {}).get("selection_mode")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or (
                    (run_universe_meta_map.get(s.strategy_run_id) or {}).get("selection_mode")
                    if s.strategy_run_id
                    else None
                ),
                "fallback_reason": (
                    (s.extra_metadata or {}).get("fallback_reason")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or (
                    (run_universe_meta_map.get(s.strategy_run_id) or {}).get("fallback_reason")
                    if s.strategy_run_id
                    else None
                ),
                "fallback_to_default_symbols": (
                    (s.extra_metadata or {}).get("fallback_to_default_symbols")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                if isinstance((s.extra_metadata or {}), dict) and (s.extra_metadata or {}).get("fallback_to_default_symbols") is not None
                else (
                    (run_universe_meta_map.get(s.strategy_run_id) or {}).get("fallback_to_default_symbols")
                    if s.strategy_run_id
                    else None
                ),
                "executed_at": s.executed_at.isoformat() if s.executed_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "funnel_result": funnel_map.get(s.id, {}).get("funnel_result"),
                "funnel_rejected_at_layer": funnel_map.get(s.id, {}).get("funnel_rejected_at_layer"),
                "funnel_rejection_reason": (
                    funnel_map.get(s.id, {}).get("funnel_rejection_reason")
                    or (
                        (s.extra_metadata or {}).get("funnel_rejection_reason")
                        if isinstance(s.extra_metadata, dict)
                        else None
                    )
                ),
                "rejection_stage": (
                    (s.extra_metadata or {}).get("watchtower_stage")
                    if isinstance(s.extra_metadata, dict)
                    else None
                ),
                "rejection_detail": (
                    (s.extra_metadata or {}).get("watchtower_reason_detail")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or (
                    (s.extra_metadata or {}).get("funnel_rejection_detail")
                    if isinstance(s.extra_metadata, dict)
                    else None
                )
                or funnel_map.get(s.id, {}).get("funnel_rejection_detail"),
                **_build_signal_quality_snapshot(s),
            }
            for s in signals
        ]
    }


@router.post("/trigger-rebalance")
async def trigger_rebalance_scan(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """手动触发一次持仓再平衡扫描（将 AI 减仓/卖出建议转为信号）"""
    account_id = await _resolve_account_id()
    from app.engine.position_rebalance_monitor import PositionRebalanceMonitor
    monitor = PositionRebalanceMonitor(session)
    result = await monitor.scan(account_id=account_id)
    await invalidate_portfolio_view_caches(account_id)
    return {"success": True, "result": result}


@router.post("/trigger-capacity-guard")
async def trigger_capacity_guard(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """手动触发一次容量守卫扫描（超出并发持仓上限时自动生成 EXIT 信号）。"""
    from app.engine.position_rebalance_monitor import PositionRebalanceMonitor
    from app.services.regime_classifier import RegimeClassifier
    from app.services.signal_quality_config import get_regime_adjusted_config, get_signal_quality_config

    account_id = await _resolve_account_id()
    current_regime = await RegimeClassifier.get_current_regime(session)
    regime_name = current_regime.regime if current_regime else None
    sq_cfg = get_signal_quality_config()
    regime_cfg = get_regime_adjusted_config(regime_name) if regime_name else {}
    max_positions = int(regime_cfg.get("MAX_CONCURRENT_POSITIONS", sq_cfg.MAX_CONCURRENT_POSITIONS))

    monitor = PositionRebalanceMonitor(session)
    result = await monitor.enforce_position_capacity(
        account_id=account_id,
        max_positions=max_positions,
        force_refresh_scores=True,
    )
    await invalidate_portfolio_view_caches(account_id)
    return {
        "success": True,
        "account_id": account_id,
        "regime": regime_name,
        "max_positions": max_positions,
        "result": result,
    }


@router.post("/trigger-decision-cycle")
async def trigger_decision_cycle(
    rescue_queued: bool = True,
    rescue_queued_minutes: int = 3,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """手动触发一次自主决策周期（处理待执行信号）"""
    if not autonomous_engine.is_running:
        raise HTTPException(status_code=409, detail="AutonomousEngine 当前已暂停")
    account_id = await _resolve_account_id()

    rescued_count = 0
    if rescue_queued:
        rescue_cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, rescue_queued_minutes))
        try:
            rescue_stmt = (
                sa_update(TradingSignal)
                .where(
                    and_(
                        TradingSignal.account_id == account_id,
                        TradingSignal.status == SignalStatus.QUEUED,
                        TradingSignal.created_at <= rescue_cutoff,
                    )
                )
                .values(status=SignalStatus.VALIDATED)
            )
            rescue_result = await session.execute(rescue_stmt)
            rescued_count = int(getattr(rescue_result, "rowcount", 0) or 0)
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass

    results = await autonomous_engine.run_decision_cycle(
        account_id=account_id,
        db=session
    )
    return {
        "success": True,
        "account_id": account_id,
        "rescued_queued": rescued_count,
        "decisions": len(results),
        "executed": sum(1 for r in results if r.get("order_id")),
        "details": results,
    }


@router.post("/trigger-full-cycle")
async def trigger_full_cycle(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """
    手动触发完整交易周期（信号生成 + 验证 + 执行）。
    与定时任务 run_daily_trading_cycle 逻辑相同，但跳过市场时段守卫，
    适合在非标准时段调试或补跑当日周期。
    """
    if not autonomous_engine.is_running:
        raise HTTPException(status_code=409, detail="AutonomousEngine 当前已暂停")

    from app.core.runtime_config import get_autonomy_level
    from app.engine.quant_trading_loop import QuantTradingLoop

    level = await get_autonomy_level()
    account_id = await _resolve_account_id()
    should_execute = level in ("FULL", "SEMI")

    loop = QuantTradingLoop(session)
    results = await loop.run_full_cycle(
        account_id=account_id,
        execute_trades=should_execute,
        optimize=False,
    )

    phases = results.get("phases", {})
    sig_gen   = phases.get("signal_generation", {}).get("total_signals_generated", 0)
    sig_val   = phases.get("signal_validation", {}).get("validated_signals", 0)
    exec_info = phases.get("trade_execution", {})
    executed  = exec_info.get("executed_orders", exec_info.get("executed", 0))
    signal_generation_phase = phases.get("signal_generation", {})

    return {
        "success": True,
        "account_id": account_id,
        "autonomy_level": level,
        "signals_generated": sig_gen,
        "signals_validated": sig_val,
        "executed": executed,
        "signal_generation_summary": {
            "strategy_scope_note": signal_generation_phase.get("strategy_scope_note"),
            "strategy_runs_processed": signal_generation_phase.get("strategy_runs_processed", 0),
            "signals_before_dedup": signal_generation_phase.get("signals_before_dedup", 0),
            "signals_by_strategy": signal_generation_phase.get("signals_by_strategy", {}),
            "strategy_runs_used": signal_generation_phase.get("strategy_runs_used", []),
            "runtime_scan": signal_generation_phase.get("runtime_scan", {}),
        },
        "details": results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# V10.4 M4: 自主循环健康检查端点
# ─────────────────────────────────────────────────────────────────────────────
_HEALTH_CACHE_KEY = "v10_4:autonomy_health:latest"


@router.get("/health")
async def get_autonomy_health(
    current_user: str = Depends(get_current_user),
):
    """
    返回最新自主循环健康检查报告。

    优先从 Redis 缓存读取（每 2 分钟由 Job 刷新），
    若缓存不存在则实时执行一次全量检查（首次启动或 Redis 不可用时）。
    """
    import json as _json

    # ── 尝试读 Redis 缓存 ────────────────────────────────────────
    try:
        from app.models.db import redis_client
        if redis_client:
            raw = await redis_client.get(_HEALTH_CACHE_KEY)
            if raw:
                return _json.loads(raw)
    except Exception:
        pass

    # ── 缓存未命中：实时执行 ──────────────────────────────────────
    from app.models.db import SessionLocal
    from app.services.autonomy_health_monitor import autonomy_health_monitor

    async with SessionLocal() as db:
        report = await autonomy_health_monitor.run_all_checks(db)

    return report.to_dict()