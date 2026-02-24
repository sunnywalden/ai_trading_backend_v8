"""V10: AI 自主控制路由"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.runtime_config import (
    get_autonomy_level,
    set_autonomy_level,
    clear_autonomy_level_override,
)
from app.models.db import get_session
from app.services.autonomous_engine import autonomous_engine

router = APIRouter(prefix="/autonomy", tags=["V10-Autonomy"])


class AutonomyLevelUpdate(BaseModel):
    level: str  # FULL / SEMI / ADVISORY


class RevokeRequest(BaseModel):
    reason: str = "手动撤销"


@router.get("/status")
async def get_autonomy_status(current_user: str = Depends(get_current_user)):
    """获取 AI 自主运行状态 (V10)"""
    return {
        "level": await get_autonomy_level(),
        "paused": not autonomous_engine.is_running,
        "circuit_breaker_triggered": False,  # TODO: 从监控服务获取真实触发状态
        "daily_trades_today": 0,             # TODO: 实时统计
        "max_daily_trades": settings.MAX_DAILY_TRADES,
        "revoke_window_minutes": settings.REVOKE_WINDOW_MINUTES,
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
