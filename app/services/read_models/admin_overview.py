from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authorization_audit_log import AuthorizationAuditLog
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.services.read_models.system_monitor_workbench import (
    get_system_monitor_workbench,
)


async def get_admin_overview(db: AsyncSession) -> dict[str, Any]:
    system_monitor = await get_system_monitor_workbench(db)
    try:
        user_count = (
            await db.execute(select(func.count()).select_from(User))
        ).scalar_one()
        role_count = (
            await db.execute(select(func.count()).select_from(Role))
        ).scalar_one()
        permission_count = (
            await db.execute(select(func.count()).select_from(Permission))
        ).scalar_one()
        denial_count = (
            await db.execute(
                select(func.count())
                .select_from(AuthorizationAuditLog)
                .where(AuthorizationAuditLog.decision == "DENY")
            )
        ).scalar_one()
        latest_audit = list(
            (
                await db.execute(
                    select(AuthorizationAuditLog)
                    .order_by(AuthorizationAuditLog.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
    except Exception:
        user_count = 0
        role_count = 0
        permission_count = 0
        denial_count = 0
        latest_audit = []

    return {
        "summary": {
            "users": int(user_count or 0),
            "roles": int(role_count or 0),
            "permissions": int(permission_count or 0),
            "denied_access_events": int(denial_count or 0),
            "critical_alerts": len(
                system_monitor.get("monitoring_report", {}).get("critical_alerts", [])
            ),
        },
        "audit": [
            {
                "id": row.id,
                "username": row.username,
                "event_type": row.event_type,
                "resource": row.resource,
                "action": row.action,
                "decision": row.decision,
                "created_at": row.created_at,
            }
            for row in latest_audit
        ],
        "quick_actions": [
            {
                "label": "用户管理",
                "path": "/admin/users",
                "permission": "admin.user.manage",
            },
            {
                "label": "角色管理",
                "path": "/admin/roles",
                "permission": "admin.role.manage",
            },
            {
                "label": "权限目录",
                "path": "/admin/permissions",
                "permission": "admin.permission.read",
            },
            {
                "label": "权限审计",
                "path": "/admin/audit",
                "permission": "admin.audit.read",
            },
            {
                "label": "系统监控",
                "path": "/system-monitor",
                "permission": "admin.system.read",
            },
        ],
        "last_updated": datetime.utcnow().isoformat(),
    }
