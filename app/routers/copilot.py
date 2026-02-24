"""V10: Trading Copilot 路由"""
import uuid
from typing import Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.copilot_service import copilot_service

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
    return result


@router.get("/history")
async def get_history(
    session_id: Optional[str] = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取对话历史"""
    from sqlalchemy import text

    query = "SELECT id, role, content, model_used, action_intent, created_at FROM copilot_messages WHERE account_id=:aid"
    params: dict[str, Any] = {"aid": current_user}
    if session_id:
        query += " AND session_id=:sid"
        params["sid"] = session_id
    query += " ORDER BY created_at DESC LIMIT :limit"
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
async def morning_brief(current_user: str = Depends(get_current_user)):
    """获取今日盘前摘要 (V10 structured)"""
    return await copilot_service.morning_brief(current_user)


@router.post("/confirm/{action_id}")
async def confirm_action(
    action_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """确认并执行 Copilot 检测到的操作意图"""
    result = await copilot_service.confirm_action(current_user, action_id, session)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("reason", "Action failed"))
    return result
