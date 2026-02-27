"""V10: AI 自主控制路由"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.runtime_config import (
    get_autonomy_level,
    set_autonomy_level,
    clear_autonomy_level_override,
)
from app.models.db import get_session
from app.models.trading_signal import TradingSignal, SignalStatus
from app.services.autonomous_engine import autonomous_engine

router = APIRouter(prefix="/autonomy", tags=["V10-Autonomy"])


class AutonomyLevelUpdate(BaseModel):
    level: str  # FULL / SEMI / ADVISORY


class RevokeRequest(BaseModel):
    reason: str = "手动撤销"


@router.get("/status")
async def get_autonomy_status(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取 AI 自主运行状态 (V10)，包含实时信号流水线统计"""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 今日已执行交易数
    exec_result = await session.execute(
        select(func.count(TradingSignal.id)).where(
            and_(
                TradingSignal.account_id == settings.TIGER_ACCOUNT,
                TradingSignal.status == SignalStatus.EXECUTED,
                TradingSignal.executed_at >= today,
            )
        )
    )
    daily_trades = exec_result.scalar() or 0

    # 信号流水线各状态数量（今日）
    pipeline_result = await session.execute(
        select(TradingSignal.status, func.count(TradingSignal.id))
        .where(
            and_(
                TradingSignal.account_id == settings.TIGER_ACCOUNT,
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
                TradingSignal.account_id == settings.TIGER_ACCOUNT,
                TradingSignal.status == SignalStatus.FAILED,
                TradingSignal.created_at >= today,
            )
        )
    )
    failed_today = fail_result.scalar() or 0

    return {
        "level": await get_autonomy_level(),
        "paused": not autonomous_engine.is_running,
        "circuit_breaker_triggered": failed_today >= 3,
        "daily_trades_today": daily_trades,
        "max_daily_trades": settings.MAX_DAILY_TRADES,
        "revoke_window_minutes": settings.REVOKE_WINDOW_MINUTES,
        "signal_pipeline": pipeline,
        "failed_trades_today": failed_today,
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
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取 AI 自主决策审计日志"""
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT id, autonomy_level, decision_type, symbol, confidence_score, "
            "risk_gate_passed, order_id, revoked_at, circuit_breaker_triggered, created_at "
            "FROM autonomy_audit_log ORDER BY created_at DESC LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = result.fetchall()
    return {
        "logs": [
            {
                "id": r[0],
                "autonomy_level": r[1],
                "decision_type": r[2],
                "symbol": r[3],
                "confidence_score": float(r[4]) if r[4] else None,
                "risk_gate_passed": bool(r[5]),
                "order_id": r[6],
                "revoked_at": r[7].isoformat() if r[7] else None,
                "circuit_breaker": bool(r[8]),
                "created_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows
        ]
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
    from sqlalchemy import text
    result = await session.execute(
        select(TradingSignal)
        .where(TradingSignal.account_id == settings.TIGER_ACCOUNT)
        .order_by(TradingSignal.created_at.desc())
        .limit(limit)
    )
    signals = result.scalars().all()
    return {
        "signals": [
            {
                "signal_id": s.signal_id,
                "symbol": s.symbol,
                "type": s.signal_type.value,
                "status": s.status.value,
                "direction": s.direction,
                "quantity": s.suggested_quantity,
                "strength": round(s.signal_strength, 3),
                "priority": s.priority,
                "notes": s.notes,
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
    from app.engine.position_rebalance_monitor import PositionRebalanceMonitor
    monitor = PositionRebalanceMonitor(session)
    result = await monitor.scan(account_id=settings.TIGER_ACCOUNT)
    return {"success": True, "result": result}


@router.post("/trigger-decision-cycle")
async def trigger_decision_cycle(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """手动触发一次自主决策周期（处理待执行信号）"""
    if not autonomous_engine.is_running:
        raise HTTPException(status_code=409, detail="AutonomousEngine 当前已暂停")
    results = await autonomous_engine.run_decision_cycle(
        account_id=settings.TIGER_ACCOUNT,
        db=session
    )
    return {
        "success": True,
        "decisions": len(results),
        "executed": sum(1 for r in results if r.get("order_id")),
        "details": results,
    }