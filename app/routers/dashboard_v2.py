"""
V10: 全新Dashboard路由
提供全景式监控API
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.core.config import settings
from app.services.dashboard_v2_service import DashboardV2Service
from app.schemas.dashboard_v2 import DashboardV2Response, DashboardQuickUpdate

router = APIRouter(prefix="/dashboard/v2", tags=["Dashboard-V2"])


@router.get("/full", response_model=DashboardV2Response, summary="获取完整Dashboard")
async def get_full_dashboard(
    account_id: str = Query(None, description="账户ID，默认使用配置"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """
    获取完整Dashboard数据
    
    整合所有核心模块数据，提供全景式监控：
    - 账户概览（权益、现金、市值等）
    - 盈亏分析（日/周/月/年收益率）
    - 风险管理（Greeks、VaR、集中度等）
    - 交易信号（管道状态、待执行信号）
    - 持仓分析（持仓摘要、集中度）
    - 交易计划（执行统计、活跃计划）
    - AI洞察（机会、警告、建议）
    - 策略表现（Top策略）
    - 系统健康（API状态）
    - 市场热点
    - 待办事项
    - 性能趋势（30天）
    """
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    service = DashboardV2Service(session)
    return await service.get_full_dashboard(account_id)


@router.get("/quick", response_model=DashboardQuickUpdate, summary="快速更新")
async def get_quick_update(
    account_id: str = Query(None, description="账户ID，默认使用配置"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """
    获取快速更新（仅核心指标）
    
    用于高频刷新Dashboard核心指标：
    - 总权益
    - 今日盈亏
    - 风险等级
    - 待执行信号数
    - 待办事项数
    - 系统告警数
    
    建议刷新频率：每10-30秒
    """
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    service = DashboardV2Service(session)
    return await service.get_quick_update(account_id)
