"""
system_monitor_workbench read model — V11.1.1

Composes API monitoring stats and the scheduler job list into a single
response dict for the system monitor workbench tab.
No business logic, no writes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.api_monitoring_service import api_monitor


async def get_system_monitor_workbench(
    db: AsyncSession,  # noqa: ARG001 — kept for API uniformity
    *,
    time_range: str = "day",
) -> dict[str, Any]:
    """Return composed system-monitor data for the workbench read layer."""
    monitoring_report = await api_monitor.generate_monitoring_report()
    api_stats = await api_monitor.get_all_api_stats(time_range=time_range)

    return {
        "monitoring_report": monitoring_report,
        "api_stats": api_stats,
        "time_range": time_range,
    }
