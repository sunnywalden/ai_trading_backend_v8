from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.core.auth_context import ACCESS_MODE_RANK, UserContext
from app.core.config import settings


async def _audit_denial(
    current_user: UserContext,
    *,
    resource: str,
    action: str,
    reason: str,
) -> None:
    if not settings.RBAC_V1121_ENABLED:
        return
    try:
        from app.models.db import SessionLocal
        from app.services.rbac_service import rbac_service

        async with SessionLocal() as session:
            await rbac_service.log_authorization_event(
                session,
                current_user,
                event_type="ACCESS_CHECK",
                resource=resource,
                action=action,
                decision="DENY",
                reason=reason,
            )
    except Exception:
        return


async def ensure_permission_or_403(
    current_user: UserContext,
    permission: str,
    *,
    resource: str | None = None,
    action: str = "read",
    reason: str | None = None,
) -> UserContext:
    if not settings.AUTH_ENABLED or not settings.RBAC_V1121_ENABLED:
        return current_user
    if current_user.has_permission(permission):
        return current_user
    denial_reason = reason or f"Missing permission: {permission}"
    await _audit_denial(
        current_user,
        resource=resource or permission.split(".")[0],
        action=action,
        reason=denial_reason,
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=denial_reason)


async def ensure_any_role_or_403(
    current_user: UserContext,
    roles: set[str],
    *,
    resource: str = "authz",
    action: str = "read",
    reason: str | None = None,
) -> UserContext:
    if not settings.AUTH_ENABLED or not settings.RBAC_V1121_ENABLED:
        return current_user
    if current_user.has_any_role(roles):
        return current_user
    denial_reason = reason or f"Required role not satisfied: {', '.join(sorted(roles))}"
    await _audit_denial(
        current_user, resource=resource, action=action, reason=denial_reason
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=denial_reason)


async def ensure_access_mode_or_403(
    current_user: UserContext,
    required_mode: str,
    *,
    resource: str,
    action: str = "read",
) -> UserContext:
    if not settings.AUTH_ENABLED or not settings.RBAC_V1121_ENABLED:
        return current_user
    current_mode = (
        "standard"
        if current_user.role in {"ADMINISTRATOR", "TRADER", "RESEARCHER"}
        else "summary"
    )
    if ACCESS_MODE_RANK.get(current_mode, 0) >= ACCESS_MODE_RANK.get(required_mode, 0):
        return current_user
    denial_reason = f"Access mode {required_mode} required"
    await _audit_denial(
        current_user, resource=resource, action=action, reason=denial_reason
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=denial_reason)


def require_permission(
    permission: str, *, resource: str | None = None, action: str = "read"
):
    from app.core.auth import get_current_user_context

    async def dependency(
        current_user: UserContext = Depends(get_current_user_context),
    ) -> UserContext:
        return await ensure_permission_or_403(
            current_user,
            permission,
            resource=resource,
            action=action,
        )

    return dependency


def require_role(role: str, *, resource: str = "authz", action: str = "read"):
    return require_any_role(role, resource=resource, action=action)


def require_any_role(*roles: str, resource: str = "authz", action: str = "read"):
    from app.core.auth import get_current_user_context

    async def dependency(
        current_user: UserContext = Depends(get_current_user_context),
    ) -> UserContext:
        return await ensure_any_role_or_403(
            current_user,
            set(roles),
            resource=resource,
            action=action,
        )

    return dependency


def require_access_mode(required_mode: str, *, resource: str, action: str = "read"):
    from app.core.auth import get_current_user_context

    async def dependency(
        current_user: UserContext = Depends(get_current_user_context),
    ) -> UserContext:
        return await ensure_access_mode_or_403(
            current_user,
            required_mode,
            resource=resource,
            action=action,
        )

    return dependency
