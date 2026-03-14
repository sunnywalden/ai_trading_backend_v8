"""
dashboard_summary read model — V11.1.1

Composes system health, active positions, capital velocity, and recent
signal quality into a single response dict.  No business logic, no writes.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.capital_velocity_service import capital_velocity_service
from app.services.dashboard_service import DashboardService


async def get_dashboard_summary(
    db: AsyncSession,
    account_id: str,
) -> dict[str, Any]:
    """Return a composed dashboard summary for the workbench read layer."""
    svc = DashboardService(db)
    summary = await svc.get_summary(account_id)

    velocity = await capital_velocity_service.compute_portfolio_velocity(
        db, account_id
    )

    return {
        "account_id": account_id,
        "summary": summary,
        "capital_velocity": velocity,
    }
