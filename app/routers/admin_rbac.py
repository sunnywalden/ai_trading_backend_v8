from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_context import UserContext
from app.core.authz import require_permission
from app.models.db import get_session
from app.schemas.authz import (
    AdminAuditLogItem,
    AdminAuditLogResponse,
    AdminPermissionItem,
    AdminPermissionListResponse,
    AdminRoleCreateRequest,
    AdminRoleListItem,
    AdminRoleListResponse,
    AdminRoleUpdateRequest,
    AdminUserCreateRequest,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserRoleAssignRequest,
    AdminUserUpdateRequest,
)
from app.schemas.broker_account import (
    BrokerAccountCreateRequest,
    BrokerAccountCredentialUpsertRequest,
    BrokerAccountListResponse,
    BrokerAccountUpdateRequest,
    BrokerAccountView,
    UserBrokerAccountGrantCreateRequest,
    UserBrokerAccountGrantListResponse,
    UserBrokerAccountGrantUpdateRequest,
    UserBrokerAccountGrantView,
)
from app.services.broker_account_service import broker_account_service
from app.services.rbac_service import rbac_service

router = APIRouter(prefix="/api/v1/admin", tags=["Admin RBAC"])

USER_MANAGE_PERMISSION = "admin.user.manage"
USER_MANAGE_ACTION = "user.manage"
ROLE_MANAGE_PERMISSION = "admin.role.manage"
ROLE_MANAGE_ACTION = "role.manage"
PERMISSION_READ_PERMISSION = "admin.permission.read"
PERMISSION_READ_ACTION = "permission.read"
AUDIT_READ_PERMISSION = "admin.audit.read"
AUDIT_READ_ACTION = "audit.read"
BROKER_ACCOUNT_MANAGE_PERMISSION = "admin.broker_account.manage"
BROKER_ACCOUNT_MANAGE_ACTION = "broker_account.manage"

DbSession = Annotated[AsyncSession, Depends(get_session)]
UserManageContext = Annotated[
    UserContext,
    Depends(
        require_permission(
            USER_MANAGE_PERMISSION,
            resource="admin",
            action=USER_MANAGE_ACTION,
        )
    ),
]
RoleManageContext = Annotated[
    UserContext,
    Depends(
        require_permission(
            ROLE_MANAGE_PERMISSION,
            resource="admin",
            action=ROLE_MANAGE_ACTION,
        )
    ),
]
PermissionReadContext = Annotated[
    UserContext,
    Depends(
        require_permission(
            PERMISSION_READ_PERMISSION,
            resource="admin",
            action=PERMISSION_READ_ACTION,
        )
    ),
]
AuditReadContext = Annotated[
    UserContext,
    Depends(
        require_permission(
            AUDIT_READ_PERMISSION,
            resource="admin",
            action=AUDIT_READ_ACTION,
        )
    ),
]
BrokerAccountManageContext = Annotated[
    UserContext,
    Depends(
        require_permission(
            BROKER_ACCOUNT_MANAGE_PERMISSION,
            resource="admin",
            action=BROKER_ACCOUNT_MANAGE_ACTION,
        )
    ),
]


@router.get("/users")
async def list_users(
    session: DbSession,
    current_user: UserManageContext,
) -> AdminUserListResponse:
    del current_user
    return AdminUserListResponse(
        users=[
            AdminUserListItem.model_validate(item)
            for item in await rbac_service.list_users(session)
        ]
    )


@router.post("/users")
async def create_user(
    payload: AdminUserCreateRequest,
    session: DbSession,
    current_user: UserManageContext,
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
            action=USER_MANAGE_ACTION,
            decision="ALLOW",
            target_type="user",
            target_id=str(user["id"]),
            metadata={
                "username": user["username"],
                "role": user["default_role"],
            },
        )
        return user
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    session: DbSession,
    current_user: UserManageContext,
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
            action=USER_MANAGE_ACTION,
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


@router.post("/users/{user_id}/roles")
async def assign_role(
    user_id: int,
    payload: AdminUserRoleAssignRequest,
    session: DbSession,
    current_user: RoleManageContext,
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
            action=ROLE_MANAGE_ACTION,
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


@router.get("/roles")
async def list_roles(
    session: DbSession,
    current_user: RoleManageContext,
) -> AdminRoleListResponse:
    del current_user
    return AdminRoleListResponse(
        roles=[
            AdminRoleListItem.model_validate(item)
            for item in await rbac_service.list_roles(session)
        ]
    )


@router.post("/roles")
async def create_role(
    payload: AdminRoleCreateRequest,
    session: DbSession,
    current_user: RoleManageContext,
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
        action=ROLE_MANAGE_ACTION,
        decision="ALLOW",
        target_type="role",
        target_id=str(role["id"]),
    )
    return role


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: int,
    payload: AdminRoleUpdateRequest,
    session: DbSession,
    current_user: RoleManageContext,
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
        action=ROLE_MANAGE_ACTION,
        decision="ALLOW",
        target_type="role",
        target_id=str(role_id),
    )
    return role


@router.get("/permissions")
async def list_permissions(
    session: DbSession,
    current_user: PermissionReadContext,
) -> AdminPermissionListResponse:
    del current_user
    return AdminPermissionListResponse(
        permissions=[
            AdminPermissionItem.model_validate(item)
            for item in await rbac_service.list_permissions(session)
        ]
    )


@router.get("/audit/authz")
async def list_authz_audit(
    session: DbSession,
    current_user: AuditReadContext,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AdminAuditLogResponse:
    del current_user
    return AdminAuditLogResponse(
        items=[
            AdminAuditLogItem.model_validate(item)
            for item in await rbac_service.list_audit_logs(
                session,
                limit=limit,
            )
        ]
    )


@router.get("/broker-accounts")
async def list_broker_accounts(
    session: DbSession,
    current_user: BrokerAccountManageContext,
) -> BrokerAccountListResponse:
    del current_user
    return BrokerAccountListResponse(
        accounts=[
            BrokerAccountView.model_validate(item)
            for item in await broker_account_service.list_accounts(session)
        ]
    )


@router.post("/broker-accounts")
async def create_broker_account(
    payload: BrokerAccountCreateRequest,
    session: DbSession,
    current_user: BrokerAccountManageContext,
) -> dict:
    account = await broker_account_service.create_account(
        session,
        account_id=payload.account_id,
        display_name=payload.display_name,
        account_type=payload.account_type,
        market=payload.market,
        tiger_id=payload.tiger_id,
    )
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="BROKER_ACCOUNT_CREATED",
        resource="admin",
        action=BROKER_ACCOUNT_MANAGE_ACTION,
        decision="ALLOW",
        target_type="broker_account",
        target_id=str(account["id"]),
        metadata={"account_id": account["account_id"]},
    )
    return account


@router.patch("/broker-accounts/{account_id}")
async def update_broker_account(
    account_id: int,
    payload: BrokerAccountUpdateRequest,
    session: DbSession,
    current_user: BrokerAccountManageContext,
) -> dict:
    try:
        account = await broker_account_service.update_account(
            session,
            account_db_id=account_id,
            display_name=payload.display_name,
            account_type=payload.account_type,
            market=payload.market,
            tiger_id=payload.tiger_id,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="BROKER_ACCOUNT_UPDATED",
        resource="admin",
        action=BROKER_ACCOUNT_MANAGE_ACTION,
        decision="ALLOW",
        target_type="broker_account",
        target_id=str(account_id),
        metadata={"account_id": account["account_id"]},
    )
    return account


@router.post("/broker-accounts/{account_id}/credentials")
async def upsert_broker_account_credentials(
    account_id: int,
    payload: BrokerAccountCredentialUpsertRequest,
    session: DbSession,
    current_user: BrokerAccountManageContext,
) -> dict:
    try:
        account = await broker_account_service.upsert_credentials(
            session,
            account_db_id=account_id,
            tiger_id=payload.tiger_id,
            private_key_pem=payload.private_key_pem,
        )
        from app.broker.broker_account_registry import BrokerAccountRegistry

        model = await broker_account_service.get_account(session, account_id)
        if model is not None and model.credentials is not None:
            await BrokerAccountRegistry.register_account(
                model,
                model.credentials,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="BROKER_ACCOUNT_CREDENTIALS_UPDATED",
        resource="admin",
        action=BROKER_ACCOUNT_MANAGE_ACTION,
        decision="ALLOW",
        target_type="broker_account",
        target_id=str(account_id),
        metadata={"account_id": account["account_id"]},
    )
    return account


@router.delete("/broker-accounts/{account_id}")
async def delete_broker_account(
    account_id: int,
    session: DbSession,
    current_user: BrokerAccountManageContext,
) -> dict:
    try:
        account = await broker_account_service.deactivate_account(
            session,
            account_db_id=account_id,
        )
        from app.broker.broker_account_registry import BrokerAccountRegistry

        await BrokerAccountRegistry.deregister(account["account_id"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="BROKER_ACCOUNT_DEACTIVATED",
        resource="admin",
        action=BROKER_ACCOUNT_MANAGE_ACTION,
        decision="ALLOW",
        target_type="broker_account",
        target_id=str(account_id),
        metadata={"account_id": account["account_id"]},
    )
    return account


@router.get("/users/{user_id}/account-grants")
async def list_user_account_grants(
    user_id: int,
    session: DbSession,
    current_user: UserManageContext,
) -> UserBrokerAccountGrantListResponse:
    del current_user
    return UserBrokerAccountGrantListResponse(
        grants=[
            UserBrokerAccountGrantView.model_validate(item)
            for item in await broker_account_service.list_user_grants(
                session,
                user_id=user_id,
            )
        ]
    )


@router.post("/users/{user_id}/account-grants")
async def create_user_account_grant(
    user_id: int,
    payload: UserBrokerAccountGrantCreateRequest,
    session: DbSession,
    current_user: UserManageContext,
) -> dict:
    try:
        grant = await broker_account_service.upsert_user_grant(
            session,
            user_id=user_id,
            broker_account_id=payload.broker_account_id,
            grant_level=payload.grant_level,
            granted_by=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="ACCOUNT_GRANT_CREATED",
        resource="admin",
        action=USER_MANAGE_ACTION,
        decision="ALLOW",
        target_type="account_grant",
        target_id=f"{user_id}:{grant['account_id']}",
        metadata={"grant_level": grant["grant_level"]},
    )
    return grant


@router.patch("/users/{user_id}/account-grants/{grant_id}")
async def update_user_account_grant(
    user_id: int,
    grant_id: int,
    payload: UserBrokerAccountGrantUpdateRequest,
    session: DbSession,
    current_user: UserManageContext,
) -> dict:
    try:
        existing_grants = await broker_account_service.list_user_grants(
            session,
            user_id=user_id,
        )
        existing = next(
            (item for item in existing_grants if item["id"] == grant_id), None
        )
        if existing is None:
            raise ValueError("Account grant not found")
        grant = await broker_account_service.upsert_user_grant(
            session,
            user_id=user_id,
            broker_account_id=existing["broker_account_id"],
            grant_level=payload.grant_level,
            granted_by=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="ACCOUNT_GRANT_UPDATED",
        resource="admin",
        action=USER_MANAGE_ACTION,
        decision="ALLOW",
        target_type="account_grant",
        target_id=f"{user_id}:{grant['account_id']}",
        metadata={"grant_level": grant["grant_level"]},
    )
    return grant


@router.delete("/users/{user_id}/account-grants/{grant_id}")
async def delete_user_account_grant(
    user_id: int,
    grant_id: int,
    session: DbSession,
    current_user: UserManageContext,
) -> dict:
    try:
        grant = await broker_account_service.revoke_user_grant(
            session,
            user_id=user_id,
            grant_id=grant_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await rbac_service.log_authorization_event(
        session,
        current_user,
        event_type="ACCOUNT_GRANT_REVOKED",
        resource="admin",
        action=USER_MANAGE_ACTION,
        decision="ALLOW",
        target_type="account_grant",
        target_id=f"{user_id}:{grant['account_id']}",
        metadata={"grant_level": grant["grant_level"]},
    )
    return grant
