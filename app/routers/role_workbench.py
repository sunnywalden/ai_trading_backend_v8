from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import UserContext
from app.core.authz import require_any_role, require_permission
from app.models.db import get_session
from app.services.read_models.admin_overview import get_admin_overview
from app.services.read_models.executive_reports import (
    get_executive_performance_report,
    get_executive_risk_report,
    get_executive_summary,
)
from app.services.read_models.research_home import get_research_home
from app.services.read_models.trading_home import get_trading_home

router = APIRouter(prefix="/api/v1", tags=["Role Workbench"])


@router.get("/research/home")
async def research_home(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_any_role(
            "RESEARCHER", "ADMINISTRATOR", resource="research", action="home.read"
        )
    ),
):
    del current_user
    return await get_research_home(session)


@router.get("/trading/home")
async def trading_home(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_any_role(
            "TRADER", "ADMINISTRATOR", resource="trading", action="home.read"
        )
    ),
):
    del current_user
    return await get_trading_home(session)


@router.get("/executive/summary")
async def executive_summary(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission(
            "executive.home.read", resource="executive", action="home.read"
        )
    ),
):
    del current_user
    return await get_executive_summary(session)


@router.get("/executive/risk-report")
async def executive_risk_report(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission(
            "executive.report.risk.read",
            resource="executive",
            action="report.risk.read",
        )
    ),
):
    del current_user
    return await get_executive_risk_report(session)


@router.get("/executive/performance-report")
async def executive_performance_report(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission(
            "executive.report.performance.read",
            resource="executive",
            action="report.performance.read",
        )
    ),
):
    del current_user
    return await get_executive_performance_report(session)


@router.get("/admin/overview")
async def admin_overview(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.home.read", resource="admin", action="home.read")
    ),
):
    del current_user
    return await get_admin_overview(session)
