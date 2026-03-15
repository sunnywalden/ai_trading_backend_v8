from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.read_models.dashboard_summary import get_dashboard_summary
from app.services.read_models.system_monitor_workbench import (
    get_system_monitor_workbench,
)


async def get_executive_summary(db: AsyncSession) -> dict[str, Any]:
    dashboard = await get_dashboard_summary(db, settings.TIGER_ACCOUNT)
    system_monitor = await get_system_monitor_workbench(db)
    summary = dashboard.get("summary")
    capital_velocity = dashboard.get("capital_velocity", {})
    return {
        "summary_cards": [
            {"label": "总资产", "value": getattr(summary, "total_equity", 0)},
            {"label": "日收益率", "value": getattr(summary, "daily_return_pct", 0)},
            {"label": "风险等级", "value": getattr(summary, "risk_level", "UNKNOWN")},
            {
                "label": "资本效率",
                "value": capital_velocity.get("efficiency_grade", "UNKNOWN"),
            },
        ],
        "highlights": [
            {
                "title": "活跃计划",
                "value": getattr(summary, "active_plans_count", 0),
                "description": "主管视角优先关注计划执行率与风险等级。",
            },
            {
                "title": "系统告警",
                "value": len(
                    system_monitor.get("monitoring_report", {}).get(
                        "critical_alerts", []
                    )
                ),
                "description": "异常数来自系统监控工作台聚合。",
            },
        ],
        "reports": [
            {
                "label": "经营总览",
                "path": "/reports/executive",
                "permission": "executive.report.executive.read",
            },
            {
                "label": "风险报表",
                "path": "/reports/risk",
                "permission": "executive.report.risk.read",
            },
            {
                "label": "绩效报表",
                "path": "/reports/performance",
                "permission": "executive.report.performance.read",
            },
        ],
        "last_updated": datetime.utcnow().isoformat(),
    }


async def get_executive_risk_report(db: AsyncSession) -> dict[str, Any]:
    dashboard = await get_dashboard_summary(db, settings.TIGER_ACCOUNT)
    summary = dashboard.get("summary")
    return {
        "risk": {
            "risk_level": getattr(summary, "risk_level", "UNKNOWN"),
            "daily_return_pct": getattr(summary, "daily_return_pct", 0),
            "plan_execution_rate": getattr(summary, "plan_execution_rate", 0),
        },
        "narrative": "主管视角默认只展示收益、风险与执行率，不进入过程配置细节。",
        "last_updated": datetime.utcnow().isoformat(),
    }


async def get_executive_performance_report(db: AsyncSession) -> dict[str, Any]:
    dashboard = await get_dashboard_summary(db, settings.TIGER_ACCOUNT)
    summary = dashboard.get("summary")
    capital_velocity = dashboard.get("capital_velocity", {})
    return {
        "performance": {
            "mtd_return_pct": getattr(summary, "mtd_return_pct", 0),
            "ytd_return_pct": getattr(summary, "ytd_return_pct", 0),
            "capital_velocity_score": capital_velocity.get("score", 0),
            "capital_efficiency_grade": capital_velocity.get(
                "efficiency_grade", "UNKNOWN"
            ),
        },
        "narrative": "绩效页聚焦收益与资本效率，不暴露研究/执行配置噪声。",
        "last_updated": datetime.utcnow().isoformat(),
    }
