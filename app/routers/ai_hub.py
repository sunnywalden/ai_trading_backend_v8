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
from app.broker.factory import make_option_broker_client
from app.services.multi_agent_orchestrator import multi_agent_orchestrator
from app.services.confidence_calibration_service import confidence_calibration_service
from app.services.adaptive_factor_weighting_service import adaptive_factor_weighting_service
from app.services.decision_post_mortem_service import decision_post_mortem_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai-hub", tags=["AI 中枢 2.0 V10.3.3"])


async def _resolve_broker_account_id(current_user: str) -> str:
    """券商账号解析：优先实时获取券商账号，回退 current_user。"""
    try:
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            return str(broker_id)
    except Exception:
        pass
    return str(current_user)


class PostMortemCreateRequest(BaseModel):
    trade_id: str
    symbol: str
    direction: str  # long / short
    entry_price: float
    exit_price: float
    realized_pnl: float
    hold_days: int
    trade_context: str | None = None


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
    user_id: str = Depends(get_current_user),
):
    """触发一次新的多 Agent 协作，立即返回 run_id，后台异步执行。"""
    run_id = await multi_agent_orchestrator.submit(
        user_id=user_id,
        symbol=body.symbol,
        context=body.context or {},
        size_usd=body.size_usd,
    )
    return {"run_id": run_id, "status": "pending", "symbol": body.symbol}


@router.get("/agent-runs/{run_id}/status")
async def get_agent_run_status(
    run_id: str,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """轮询 run 执行状态：pending / running / completed / failed。
    completed 时直接返回完整结果。
    """
    state = multi_agent_orchestrator.get_run_status(run_id)
    if state is None:
        # 不在内存则查 DB（进程重启后）
        messages = await multi_agent_orchestrator.get_run_summary(db, run_id)
        if messages:
            return {"run_id": run_id, "status": "completed", "messages": messages}
        # 冷启动/异步写入窗口：尚未落地时返回 pending，避免前端轮询 404 抖动
        return {"run_id": run_id, "status": "pending"}

    if state.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    if state["status"] == "completed":
        return {"run_id": run_id, "status": "completed", **state.get("result", {})}
    if state["status"] == "failed":
        return {"run_id": run_id, "status": "failed", "error": state.get("error", "unknown")}
    return {"run_id": run_id, "status": state["status"]}


@router.get("/agent-runs/{run_id}")
async def get_agent_run(
    run_id: str,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回指定 run_id 的完整消息序列。"""
    # 先检查内存状态（completed 时有缓存结果）
    state = multi_agent_orchestrator.get_run_status(run_id)
    if state and state.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if state and state["status"] == "completed" and "result" in state:
        res = state["result"]
        return {
            "run_id": run_id,
            "status": "completed",
            "symbol": res.get("symbol"),
            "final_decision": res.get("final_decision"),
            "final_confidence": res.get("final_confidence"),
            "orchestrator_summary": res.get("orchestrator_summary"),
            "challenge_points": res.get("challenge_points", []),
            "messages": res.get("messages", []),
            "latency_ms": res.get("latency_ms"),
        }
    if state and state["status"] in ("pending", "running"):
        return {"run_id": run_id, "status": state["status"], "messages": []}

    # 从 DB 查
    messages = await multi_agent_orchestrator.get_run_summary(db, run_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Agent run not found")
    from sqlalchemy import select
    from app.models.agent_communication_log import AgentCommunicationLog
    stmt = select(AgentCommunicationLog.user_id).where(
        AgentCommunicationLog.run_id == run_id
    ).limit(1)
    row = (await db.execute(stmt)).first()
    if row and row.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return {"run_id": run_id, "status": "completed", "messages": messages}


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
    account_id = await _resolve_broker_account_id(user_id)
    result = await confidence_calibration_service.get_latest_calibration(db, account_id)
    if not result:
        # 懒初始化：首次访问时自动尝试跑一次，避免页面长时间空白
        snap = await confidence_calibration_service.run_daily_calibration(db, account_id)
        await db.commit()
        result = await confidence_calibration_service.get_latest_calibration(db, account_id)
        logger.info(
            "[Calibration] lazy init run for account=%s total_samples=%s ece=%s",
            account_id,
            getattr(snap, "total_samples", None),
            getattr(snap, "ece", None),
        )
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
    account_id = await _resolve_broker_account_id(user_id)
    rows = await confidence_calibration_service.get_calibration_history(db, account_id, days=days)
    if rows:
        return rows

    # 历史为空时也尝试懒初始化一次，返回至少一个快照给前端
    snap = await confidence_calibration_service.run_daily_calibration(db, account_id)
    await db.commit()
    logger.info(
        "[Calibration] history lazy init run for account=%s total_samples=%s ece=%s",
        account_id,
        getattr(snap, "total_samples", None),
        getattr(snap, "ece", None),
    )
    return await confidence_calibration_service.get_calibration_history(db, account_id, days=days)


@router.post("/calibration/run")
async def run_calibration(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """手动触发今日置信度校准（日常由 APScheduler 在 08:15 自动运行）。"""
    account_id = await _resolve_broker_account_id(user_id)
    snap = await confidence_calibration_service.run_daily_calibration(db, account_id)
    await db.commit()
    return {"message": "Calibration completed", "snapshot_date": str(snap.snapshot_date), "ece": snap.ece}


# ─────────────────── Adaptive Factor Weights ───────────────────────────────

@router.get("/factor-weights")
async def get_factor_weights(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回当前最新自适应因子权重。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await adaptive_factor_weighting_service.get_current_weights(db, account_id)


@router.get("/factor-weights/history")
async def get_factor_weights_history(
    days: int = Query(default=30, ge=7, le=90),
    dimension: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回权重演化历史。可按 dimension 过滤。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await adaptive_factor_weighting_service.get_weights_history(db, account_id, days=days, dimension=dimension)


@router.get("/factor-momentum")
async def get_factor_momentum(
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最新因子 IC 动量排名。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await adaptive_factor_weighting_service.get_factor_momentum(db, account_id)


# ─────────────────── Decision Post-Mortem ──────────────────────────────────

@router.get("/post-mortems")
async def get_post_mortems(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回最近 N 笔决策事后剖析报告。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await decision_post_mortem_service.get_post_mortems(db, account_id, limit=limit)


@router.get("/post-mortems/trade-candidates")
async def get_post_mortem_trade_candidates(
    limit: int = Query(default=100, ge=1, le=500),
    q: str | None = Query(default=None, description="按 symbol 关键字过滤"),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回可下拉选择的候选交易列表（自动排除已剖析记录）。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await decision_post_mortem_service.list_trade_candidates(db, account_id, limit=limit, q=q)


@router.get("/post-mortems/trade-candidates/{trade_id}")
async def get_post_mortem_trade_prefill(
    trade_id: str,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回候选交易的预填参数，供前端一键带入表单。"""
    account_id = await _resolve_broker_account_id(user_id)
    payload = await decision_post_mortem_service.get_trade_prefill(db, account_id, trade_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Trade candidate not found")
    return payload


@router.get("/post-mortems/patterns")
async def get_post_mortem_patterns(
    days: int = Query(default=90, ge=30, le=365),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """汇总常见决策错误模式和认知偏见。"""
    account_id = await _resolve_broker_account_id(user_id)
    return await decision_post_mortem_service.get_patterns(db, account_id, days=days)


@router.get("/post-mortems/{trade_id}")
async def get_post_mortem_by_trade(
    trade_id: str,
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """返回指定 trade_id 的事后剖析报告。"""
    account_id = await _resolve_broker_account_id(user_id)
    result = await decision_post_mortem_service.get_by_trade_id(db, account_id, trade_id)
    if not result:
        raise HTTPException(status_code=404, detail="Post-mortem not found")
    return result


@router.post("/post-mortems")
async def create_post_mortem(
    body: PostMortemCreateRequest = Body(...),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    """创建（或返回已有）单笔交易的 AI 事后剖析报告。"""
    # 统一方向映射到服务内部提示语义
    direction = (body.direction or "").strip().upper()
    if direction in {"LONG", "BUY", "B"}:
        direction = "BUY"
    elif direction in {"SHORT", "SELL", "S"}:
        direction = "SELL"
    else:
        direction = "BUY"

    context_payload = {"user_context": body.trade_context} if body.trade_context else {}
    account_id = await _resolve_broker_account_id(user_id)
    pm = await decision_post_mortem_service.generate_post_mortem(
        db=db,
        account_id=account_id,
        trade_id=body.trade_id,
        symbol=body.symbol,
        direction=direction,
        entry_price=body.entry_price,
        exit_price=body.exit_price,
        realized_pnl=body.realized_pnl,
        hold_days=max(int(body.hold_days or 1), 1),
        trade_context=context_payload,
    )
    await db.commit()
    return await decision_post_mortem_service.get_by_trade_id(db, account_id, pm.trade_id)
