"""V10.3.3 AI 中枢 2.0 API 路由

端点：
  GET  /api/v1/ai-hub/agent-runs                    — 历史 Agent 运行记录
  POST /api/v1/ai-hub/agent-runs                    — 触发新一轮 Agent 协作
  GET  /api/v1/ai-hub/agent-runs/{run_id}           — 获取指定 run 详情
  GET  /api/v1/ai-hub/agent-runs/{run_id}/challenge — 获取 RiskChallengerAgent 反驳要点
  GET  /api/v1/ai-hub/calibration                   — 最新置信度校准快照
  GET  /api/v1/ai-hub/calibration/history           — 置信度校准历史
  POST /api/v1/ai-hub/calibration/run               — 手动触发校准（内部/admin）
  GET  /api/v1/ai-hub/factor-weights                — 当前自适应因子权重
  GET  /api/v1/ai-hub/factor-weights/history        — 权重演化历史
  GET  /api/v1/ai-hub/factor-momentum               — 因子动量排名
  GET  /api/v1/ai-hub/post-mortems                  — 决策事后剖析列表
  GET  /api/v1/ai-hub/post-mortems/{trade_id}       — 单笔事后剖析详情
  GET  /api/v1/ai-hub/post-mortems/patterns         — 错误模式汇总
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.multi_agent_orchestrator import multi_agent_orchestrator
from app.services.confidence_calibration_service import confidence_calibration_service
from app.services.adaptive_factor_weighting_service import adaptive_factor_weighting_service
from app.services.decision_post_mortem_service import decision_post_mortem_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai-hub", tags=["AI 中枢 2.0 V10.3.3"])


# ─────────────────── Multi-Agent Orchestration ─────────────────────────────

class AgentRunRequest(BaseModel):
    symbol: str
    context: dict | None = None
    size_usd: float = 10000.0


@router.get("/agent-runs")
async def list_agent_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最近 N 次 Agent 协作运行记录（每次只显示 Orchestrator 决策行）。"""
    return await multi_agent_orchestrator.list_runs(db, user_id, limit=limit)


@router.post("/agent-runs")
async def trigger_agent_run(
    body: AgentRunRequest,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """触发一次新的多 Agent 协作，返回完整决策结果。"""
    result = await multi_agent_orchestrator.run(
        db,
        user_id=user_id,
        symbol=body.symbol,
        context=body.context or {},
        size_usd=body.size_usd,
    )
    await db.commit()
    return result.model_dump()


@router.get("/agent-runs/{run_id}")
async def get_agent_run(
    run_id: str,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回指定 run_id 的完整消息序列。"""
    messages = await multi_agent_orchestrator.get_run_summary(db, run_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Agent run not found")
    # 基本权限校验：确保属于当前用户
    from sqlalchemy import select
    from app.models.agent_communication_log import AgentCommunicationLog
    stmt = select(AgentCommunicationLog.user_id).where(
        AgentCommunicationLog.run_id == run_id
    ).limit(1)
    row = (await db.execute(stmt)).first()
    if row and row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return {"run_id": run_id, "messages": messages}


@router.get("/agent-runs/{run_id}/challenge")
async def get_agent_challenge(
    run_id: str,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回指定 run 中 RiskChallengerAgent 的反驳要点。"""
    from sqlalchemy import select
    from app.models.agent_communication_log import AgentCommunicationLog
    stmt = (
        select(AgentCommunicationLog)
        .where(
            AgentCommunicationLog.run_id == run_id,
            AgentCommunicationLog.agent_id == "RiskChallengerAgent",
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Challenge not found for this run")
    if row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return {
        "run_id": run_id,
        "challenge_points": (row.structured_output or {}).get("challenge_points", []),
        "overall_risk_level": (row.structured_output or {}).get("overall_risk_level", "MEDIUM"),
        "veto_recommendation": (row.structured_output or {}).get("veto_recommendation", False),
        "full_content": row.content[:1000],
    }


# ─────────────────── Confidence Calibration ────────────────────────────────

@router.get("/calibration")
async def get_calibration(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最新置信度校准快照。"""
    result = await confidence_calibration_service.get_latest_calibration(db, user_id)
    if not result:
        return {"message": "No calibration data available yet. Run daily calibration first."}
    return result


@router.get("/calibration/history")
async def get_calibration_history(
    days: int = Query(default=30, ge=7, le=90),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回过去 N 天置信度校准历史。"""
    return await confidence_calibration_service.get_calibration_history(db, user_id, days=days)


@router.post("/calibration/run")
async def run_calibration(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """手动触发今日置信度校准（日常由 APScheduler 在 08:15 自动运行）。"""
    snap = await confidence_calibration_service.run_daily_calibration(db, user_id)
    await db.commit()
    return {"message": "Calibration completed", "snapshot_date": str(snap.snapshot_date), "ece": snap.ece}


# ─────────────────── Adaptive Factor Weights ───────────────────────────────

@router.get("/factor-weights")
async def get_factor_weights(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回当前最新自适应因子权重。"""
    return await adaptive_factor_weighting_service.get_current_weights(db, user_id)


@router.get("/factor-weights/history")
async def get_factor_weights_history(
    days: int = Query(default=30, ge=7, le=90),
    dimension: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回权重演化历史。可按 dimension 过滤。"""
    return await adaptive_factor_weighting_service.get_weights_history(db, user_id, days=days, dimension=dimension)


@router.get("/factor-momentum")
async def get_factor_momentum(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最新因子 IC 动量排名。"""
    return await adaptive_factor_weighting_service.get_factor_momentum(db, user_id)


# ─────────────────── Decision Post-Mortem ──────────────────────────────────

@router.get("/post-mortems")
async def get_post_mortems(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最近 N 笔决策事后剖析报告。"""
    return await decision_post_mortem_service.get_post_mortems(db, user_id, limit=limit)


@router.get("/post-mortems/patterns")
async def get_post_mortem_patterns(
    days: int = Query(default=90, ge=30, le=365),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """汇总常见决策错误模式和认知偏见。"""
    return await decision_post_mortem_service.get_patterns(db, user_id, days=days)


@router.get("/post-mortems/{trade_id}")
async def get_post_mortem_by_trade(
    trade_id: str,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回指定 trade_id 的事后剖析报告。"""
    result = await decision_post_mortem_service.get_by_trade_id(db, user_id, trade_id)
    if not result:
        raise HTTPException(status_code=404, detail="Post-mortem not found")
    return result
