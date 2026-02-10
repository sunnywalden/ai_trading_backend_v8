"""V9: Dashboard 路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.core.config import settings
from app.broker.factory import make_option_broker_client
from app.services.dashboard_service import DashboardService
from app.schemas.dashboard import DashboardSummaryResponse

router = APIRouter(prefix="/dashboard", tags=["V9-Dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取 Dashboard 一页汇总"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = DashboardService(session)
    return await svc.get_summary(account_id)
