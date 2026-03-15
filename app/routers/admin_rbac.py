from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import UserContext
from app.core.authz import require_permission
from app.models.db import get_session
from app.schemas.authz import (
    AdminAuditLogResponse,
    AdminPermissionListResponse,
    AdminRoleCreateRequest,
    AdminRoleListResponse,
    AdminRoleUpdateRequest,
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserRoleAssignRequest,
    AdminUserUpdateRequest,
)
from app.services.rbac_service import rbac_service

router = APIRouter(prefix="/api/v1/admin", tags=["Admin RBAC"])


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.user.manage", resource="admin", action="user.manage")
    ),
) -> AdminUserListResponse:
    del current_user
    return AdminUserListResponse(users=await rbac_service.list_users(session))


@router.post("/users", response_model=dict)
async def create_user(
    payload: AdminUserCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.user.manage", resource="admin", action="user.manage")
    ),
) -> dict:
    try:
        user = await rbac_service.create_user(
            session,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            role_code=payload.role_code,
            assigned_by=current_user.username,
        )
        await rbac_service.log_authorization_event(
            session,
            current_user,
            event_type="USER_CREATED",
            resource="admin",
            action="user.manage",
            decision="ALLOW",
            target_type="user",
            target_id=str(user["id"]),
            metadata={"username": user["username"], "role": user["default_role"]},
        )
        return user
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.patch("/users/{user_id}", response_model=dict)
async def update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.user.manage", resource="admin", action="user.manage")
    ),
) -> dict:
    try:
        user = await rbac_service.update_user(
            session,
            user_id=user_id,
            display_name=payload.display_name,
            password=payload.password,
            status=payload.status,
            role_code=payload.role_code,
            assigned_by=current_user.username,
        )
        await rbac_service.log_authorization_event(
            session,
            current_user,
            event_type="USER_UPDATED",
            resource="admin",
            action="user.manage",
            decision="ALLOW",
            target_type="user",
            target_id=str(user_id),
            metadata={"role": user["default_role"], "status": user["status"]},
        )
        return user
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/users/{user_id}/roles", response_model=dict)
async def assign_role(
    user_id: int,
    payload: AdminUserRoleAssignRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.role.manage", resource="admin", action="role.manage")
    ),
) -> dict:
    try:
        updated = await rbac_service.update_user(
            session,
            user_id=user_id,
            role_code=payload.role_code,
            assigned_by=current_user.username,
        )
        await rbac_service.log_authorization_event(
            session,
            current_user,
            event_type="ROLE_ASSIGNED",
            resource="admin",
            action="role.manage",
            decision="ALLOW",
            target_type="user",
            target_id=str(user_id),
            metadata={"role": payload.role_code},
        )
        return updated
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/roles", response_model=AdminRoleListResponse)
async def list_roles(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.role.manage", resource="admin", action="role.manage")
    ),
) -> AdminRoleListResponse:
    del current_user
    return AdminRoleListResponse(roles=await rbac_service.list_roles(session))


@router.post("/roles", response_model=dict)
async def create_role(
    payload: AdminRoleCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.role.manage", resource="admin", action="role.manage")
    ),
) -> dict:
    role = await rbac_service.upsert_role(
        session,
        role_id=None,
        code=payload.code,
        name=payload.name,
        description=payload.description,
    )
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="ROLE_CREATED",
        resource="admin",
        action="role.manage",
        decision="ALLOW",
        target_type="role",
        target_id=str(role["id"]),
    )
    return role


@router.patch("/roles/{role_id}", response_model=dict)
async def update_role(
    role_id: int,
    payload: AdminRoleUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.role.manage", resource="admin", action="role.manage")
    ),
) -> dict:
    role = await rbac_service.upsert_role(
        session,
        role_id=role_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
    )
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="ROLE_UPDATED",
        resource="admin",
        action="role.manage",
        decision="ALLOW",
        target_type="role",
        target_id=str(role_id),
    )
    return role


@router.get("/permissions", response_model=AdminPermissionListResponse)
async def list_permissions(
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission(
            "admin.permission.read", resource="admin", action="permission.read"
        )
    ),
) -> AdminPermissionListResponse:
    del current_user
    return AdminPermissionListResponse(
        permissions=await rbac_service.list_permissions(session)
    )


@router.get("/audit/authz", response_model=AdminAuditLogResponse)
async def list_authz_audit(
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    current_user: UserContext = Depends(
        require_permission("admin.audit.read", resource="admin", action="audit.read")
    ),
) -> AdminAuditLogResponse:
    del current_user
    return AdminAuditLogResponse(
        items=await rbac_service.list_audit_logs(session, limit=limit)
    )
