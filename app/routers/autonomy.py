"""V10: AI 自主控制路由"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.models.db import get_session
from app.services.autonomous_engine import autonomous_engine

router = APIRouter(prefix="/autonomy", tags=["V10-Autonomy"])


class AutonomyLevelUpdate(BaseModel):
    level: str  # FULL / SEMI / ADVISORY


class RevokeRequest(BaseModel):
    reason: str = "手动撤销"


@router.get("/status")
async def get_autonomy_status(current_user: str = Depends(get_current_user)):
    """获取 AI 自主运行状态"""
    return {
        "autonomy_level": settings.AI_AUTONOMY_LEVEL,
        "allowed_asset_types": settings.ALLOWED_ASSET_TYPES,
        "max_single_position_pct": settings.MAX_SINGLE_POSITION_PCT,
        "max_var_pct": settings.MAX_VAR_PCT,
        "max_daily_trades": settings.MAX_DAILY_TRADES,
        "max_daily_loss_pct": settings.MAX_DAILY_LOSS_PCT,
        "revoke_window_minutes": settings.REVOKE_WINDOW_MINUTES,
        "ai_lightweight_model": settings.AI_LIGHTWEIGHT_MODEL,
        "ai_complex_model": settings.AI_COMPLEX_MODEL,
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
    # 注意：settings 在进程内修改不持久化到 .env，重启后复原
    # 生产环境应写入数据库配置表
    settings.AI_AUTONOMY_LEVEL = body.level
    return {"success": True, "autonomy_level": body.level}


@router.post("/pause")
async def pause_autonomy(current_user: str = Depends(get_current_user)):
    """紧急暂停 AI（切换为 ADVISORY 模式）"""
    settings.AI_AUTONOMY_LEVEL = "ADVISORY"
    return {"success": True, "autonomy_level": "ADVISORY", "message": "AI 自主交易已暂停，切换为建议模式"}


@router.post("/resume")
async def resume_autonomy(current_user: str = Depends(get_current_user)):
    """恢复 AI 为 SEMI 模式"""
    settings.AI_AUTONOMY_LEVEL = "SEMI"
    return {"success": True, "autonomy_level": "SEMI", "message": "AI 已恢复半自主模式"}


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
    body: RevokeRequest = None,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """在 30 分钟窗口内撤销 AI 自动执行的订单"""
    reason = body.reason if body else "手动撤销"
    result = await autonomous_engine.revoke_order("default", exec_id, reason, session)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return result
