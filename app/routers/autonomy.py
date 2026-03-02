"""V10: AI 自主控制路由"""
from datetime import datetime, timezone, timedelta
from typing import Optional
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
from app.services.autonomous_engine import autonomous_engine

router = APIRouter(prefix="/autonomy", tags=["V10-Autonomy"])


class AutonomyLevelUpdate(BaseModel):
    level: str  # FULL / SEMI / ADVISORY


class RevokeRequest(BaseModel):
    reason: str = "手动撤销"


async def _resolve_account_id() -> str:
    """优先解析 Tiger 实际账户号，避免 settings.TIGER_ACCOUNT 与真实账户不一致。"""
    try:
        broker = make_option_broker_client()
        real_acc = await broker.get_account_id()
        if real_acc:
            return str(real_acc)
    except Exception:
        pass
    return settings.TIGER_ACCOUNT


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

        orders = await asyncio.to_thread(_fetch_orders)
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
        "max_daily_trades": settings.MAX_DAILY_TRADES,
        "revoke_window_minutes": settings.REVOKE_WINDOW_MINUTES,
        "signal_pipeline": pipeline,
        "failed_trades_today": failed_today,
        "cooldown_symbols": cooldown_symbols,
        "cooldown_minutes": cooldown_min,
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
    from sqlalchemy import text
    result = await session.execute(
        select(TradingSignal)
        .where(TradingSignal.account_id == account_id)
        .order_by(TradingSignal.created_at.desc())
        .limit(limit)
    )
    signals = result.scalars().all()

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

    return {
        "signals": [
            {
                "signal_id": s.signal_id,
                "symbol": s.symbol,
                "type": s.signal_type.value,
                "status": s.status.value,
                "direction": s.direction,
                "quantity": s.suggested_quantity,
                "quantity_mode": s.quantity_mode,
                "quantity_value": s.quantity_value,
                "strength": round(s.confidence, 4) if s.confidence is not None else 0.0,  # 修复置信度显示：保留4位精度(前端*100后含2位小数)
                "priority": s.priority,
                "notes": intent_map.get(s.signal_id) or s.notes,
                "order_id": s.order_id,
                "executed_at": s.executed_at.isoformat() if s.executed_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
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
    return {"success": True, "result": result}


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
    executed  = exec_info.get("executed", 0)

    return {
        "success": True,
        "account_id": account_id,
        "autonomy_level": level,
        "signals_generated": sig_gen,
        "signals_validated": sig_val,
        "executed": executed,
        "details": results,
    }