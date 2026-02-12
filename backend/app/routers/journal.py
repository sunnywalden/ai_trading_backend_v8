"""V9: 交易日志路由"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.core.config import settings
from app.broker.factory import make_option_broker_client
from app.services.journal_service import JournalService
from app.schemas.journal import (
    JournalCreateRequest, JournalUpdateRequest, JournalView,
    JournalListResponse, JournalAiReviewResponse, JournalWeeklyReportResponse,
)

router = APIRouter(prefix="/journal", tags=["V9-Journal"])


@router.post("", response_model=JournalView)
async def create_journal(
    payload: JournalCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """创建交易日志"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = JournalService(session)
    journal = await svc.create_journal(account_id, payload.model_dump(exclude_none=True))
    return JournalView.model_validate(journal, from_attributes=True)


@router.put("/{journal_id}", response_model=JournalView)
async def update_journal(
    journal_id: int,
    payload: JournalUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """更新交易日志"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = JournalService(session)
    journal = await svc.update_journal(journal_id, account_id, payload.model_dump(exclude_none=True))
    if not journal:
        raise HTTPException(status_code=404, detail="Journal not found")
    return JournalView.model_validate(journal, from_attributes=True)


@router.get("", response_model=JournalListResponse)
async def list_journals(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    account_id: Optional[str] = Query(None, description="子账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取交易日志列表"""
    # 如果没传 account_id，则从 Broker 获取默认账户
    if not account_id:
        broker = make_option_broker_client()
        account_id = await broker.get_account_id()
    
    svc = JournalService(session)
    journals, total = await svc.list_journals(account_id, page, size, symbol, status)
    items = [JournalView.model_validate(j, from_attributes=True) for j in journals]
    return JournalListResponse(items=items, total=total, page=page, size=size)


@router.post("/{journal_id}/ai-review", response_model=JournalAiReviewResponse)
async def ai_review_journal(
    journal_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """AI 自动复盘"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = JournalService(session)
    review = await svc.ai_review(journal_id, account_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Journal not found")
    return JournalAiReviewResponse(journal_id=journal_id, ai_review=review)


@router.get("/weekly-report", response_model=JournalWeeklyReportResponse)
async def weekly_report(
    week_date: date = Query(default=None, description="周内任意日期, 默认本周"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """AI 周报"""
    if week_date is None:
        week_date = date.today()
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = JournalService(session)
    result = await svc.weekly_report(account_id, week_date)
    return JournalWeeklyReportResponse(**result)
