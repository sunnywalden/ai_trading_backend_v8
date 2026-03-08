"""V10: Trading Copilot 路由"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.copilot_message import CopilotMessage
from app.models.db import get_session
from app.models.trading_plan import TradingPlan
from app.models.trading_signal import TradingSignal
from app.services.copilot_service import copilot_service

# 无独立 ORM 模型的辅助表，使用模块级常量集中管理
_ALERT_RECORDS_TABLE = "alert_records"
_MARKET_REGIME_SNAPSHOTS_TABLE = "market_regime_snapshots"

router = APIRouter(prefix="/copilot", tags=["V10-Copilot"])


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ConfirmActionRequest(BaseModel):
    action_id: str


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """发送消息给 Trading Copilot"""
    session_id = body.session_id or str(uuid.uuid4())
    result = await copilot_service.chat(
        account_id=current_user,
        session_id=session_id,
        message=body.message,
        db=session,
    )
    # 前端 normalizeMessage 读取 content 字段，将 message 映射到 content
    return {
        "id": result.get("id"),
        "role": "assistant",
        "content": result.get("message", ""),
        "model_used": result.get("model_used"),
        "action_intent": result.get("action_intent"),
        "session_id": result.get("session_id"),
        "tokens_used": result.get("tokens_used"),
        "requires_confirmation": result.get("requires_confirmation", False),
    }


@router.get("/history")
async def get_history(
    session_id: Optional[str] = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取对话历史"""
    from sqlalchemy import text

    query = (
        "SELECT id, role, content, model_used, action_intent, created_at "
        f"FROM {CopilotMessage.__tablename__} WHERE account_id=:aid"
    )
    params: dict[str, Any] = {"aid": current_user}
    if session_id:
        query += " AND session_id=:sid"
        params["sid"] = session_id
    # 用 id 排序（自增主键），避免同批次保存的 user/assistant 消息时间戳相同导致顺序不确定
    query += " ORDER BY id DESC LIMIT :limit"
    params["limit"] = limit

    result = await session.execute(text(query), params)
    rows = result.fetchall()
    return {
        "messages": [
            {
                "id": r[0],
                "role": r[1],
                "content": r[2],
                "model_used": r[3],
                "action_intent": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in reversed(rows)
        ]
    }


@router.get("/morning-brief")
async def morning_brief(
    refresh: bool = False, current_user: str = Depends(get_current_user)
):
    """获取今日盘前摘要 (V10 structured)"""
    return await copilot_service.morning_brief(current_user, force_refresh=refresh)


@router.post("/confirm/{action_id}")
async def confirm_action(
    action_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """确认并执行 Copilot 检测到的操作意图"""
    result = await copilot_service.confirm_action(current_user, action_id, session)
    if not result["success"]:
        raise HTTPException(
            status_code=400, detail=result.get("reason", "Action failed")
        )
    return result


class DeepResearchRequest(BaseModel):
    symbol: str
    query: Optional[str] = None


@router.post("/deep-research")
async def deep_research(
    body: DeepResearchRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """M7 深度研究: 6 数据源 + deepseek-reasoner 生成结构化研究报告"""
    from app.services.copilot_partner_service import copilot_partner_service

    report = await copilot_partner_service.deep_research.research(
        symbol=body.symbol.upper(),
        query=body.query or f"Comprehensive analysis of {body.symbol}",
        db=session,
    )
    return {"report": report.to_dict()}


@router.get("/context")
async def get_copilot_context(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """
    V10.4 M1 — 获取 Copilot 系统上下文快照

    为 CopilotFloatingWidget 提供跨页面感知所需的实时状态：
    - 当前市场体制（regime）
    - 活跃持仓数 / 今日信号数
    - 未处理警报数
    - LLM 提供商健康状态
    - 最新宏观风险评分
    """
    from sqlalchemy import text

    from app.services.ai_client_manager import get_circuit_breaker_status

    ctx: Dict[str, Any] = {
        "account_id": current_user,
        "snapshot_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    # ─── 活跃持仓 ───
    try:
        r = await session.execute(
            text(
                f"SELECT COUNT(*) FROM {TradingPlan.__tablename__} "
                "WHERE account_id=:aid "
                "AND UPPER(plan_status) IN ('ACTIVE','PARTIAL')"
            ),
            {"aid": current_user},
        )
        ctx["active_positions"] = r.scalar() or 0
    except Exception:
        ctx["active_positions"] = None

    # ─── 今日信号数 ───
    try:
        r = await session.execute(
            text(
                f"SELECT COUNT(*) FROM {TradingSignal.__tablename__} "
                "WHERE account_id=:aid AND DATE(created_at)=CURDATE()"
            ),
            {"aid": current_user},
        )
        ctx["today_signals"] = r.scalar() or 0
    except Exception:
        try:
            r = await session.execute(
                text(
                    f"SELECT COUNT(*) FROM {TradingSignal.__tablename__} "
                    "WHERE account_id=:aid AND DATE(created_at)=DATE('now')"
                ),
                {"aid": current_user},
            )
            ctx["today_signals"] = r.scalar() or 0
        except Exception:
            ctx["today_signals"] = None

    # ─── 未处理警报数 ───
    try:
        r = await session.execute(
            text(
                f"SELECT COUNT(*) FROM {_ALERT_RECORDS_TABLE} "
                "WHERE account_id=:aid AND is_read=0"
            ),
            {"aid": current_user},
        )
        ctx["unread_alerts"] = r.scalar() or 0
    except Exception:
        ctx["unread_alerts"] = None

    # ─── 最新市场体制 ───
    try:
        r = await session.execute(
            text(
                f"SELECT regime_label FROM {_MARKET_REGIME_SNAPSHOTS_TABLE} ORDER BY created_at DESC LIMIT 1"
            )
        )
        row = r.fetchone()
        ctx["market_regime"] = row[0] if row else None
    except Exception:
        ctx["market_regime"] = None

    # ─── 宏观风险评分 ───
    try:
        r = await session.execute(
            text(
                "SELECT composite_score FROM macro_risk_scores ORDER BY created_at DESC LIMIT 1"
            )
        )
        row = r.fetchone()
        ctx["macro_risk_score"] = float(row[0]) if row else None
    except Exception:
        ctx["macro_risk_score"] = None

    # ─── LLM 健康状态 ───
    ctx["llm_status"] = get_circuit_breaker_status()

    return ctx
