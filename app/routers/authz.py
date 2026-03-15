from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user_context
from app.core.auth_context import UserContext
from app.core.config import settings
from app.models.db import get_session
from app.schemas.authz import (
    AuthPermissionsResponse,
    AuthUserView,
    ChangePasswordRequest,
    ChangePasswordResponse,
)
from app.schemas.broker_account import AccessibleAccountView, MyAccountsResponse
from app.services.broker_account_service import broker_account_service
from app.services.rbac_service import rbac_service

router = APIRouter(prefix="/api/v1/auth", tags=["AuthZ"])


def _feature_flags_payload() -> dict[str, bool]:
    return {
        "RBAC_V1121_ENABLED": settings.RBAC_V1121_ENABLED,
        "ROLE_HOME_V1121_ENABLED": settings.ROLE_HOME_V1121_ENABLED,
        "ROLE_NAV_GATING_V1121_ENABLED": (settings.ROLE_NAV_GATING_V1121_ENABLED),
        "ROLE_ACTION_GATING_V1121_ENABLED": (settings.ROLE_ACTION_GATING_V1121_ENABLED),
        "EXECUTIVE_REPORTS_V1121_ENABLED": (settings.EXECUTIVE_REPORTS_V1121_ENABLED),
        "ADMIN_CONSOLE_V1121_ENABLED": settings.ADMIN_CONSOLE_V1121_ENABLED,
        "MULTI_ACCOUNT_V1131_ENABLED": settings.MULTI_ACCOUNT_V1131_ENABLED,
        "BROKER_ACCOUNT_REGISTRY_V1131_ENABLED": (
            settings.BROKER_ACCOUNT_REGISTRY_V1131_ENABLED
        ),
        "ACCOUNT_DATA_ISOLATION_V1131_ENABLED": (
            settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED
        ),
        "ACCOUNT_ADMIN_UI_V1131_ENABLED": (settings.ACCOUNT_ADMIN_UI_V1131_ENABLED),
    }


@router.post("/logout")
async def logout() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/me")
async def get_me(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[UserContext, Depends(get_current_user_context)],
) -> AuthUserView:
    raw_accessible_accounts = (
        await broker_account_service.list_accessible_accounts_for_context(
            session,
            current_user,
        )
    )
    accessible_accounts = [
        AccessibleAccountView.model_validate(item) for item in raw_accessible_accounts
    ]
    return AuthUserView(
        id=current_user.user_id,
        username=current_user.username,
        display_name=current_user.display_name,
        role=current_user.role,
        permissions=sorted(current_user.permissions),
        permissions_version=current_user.permissions_version,
        status=current_user.status,
        is_system_seed=current_user.is_system_seed,
        must_change_password=current_user.must_change_password,
        feature_flags=_feature_flags_payload(),
        accessible_account_ids=current_user.accessible_account_ids,
        default_account_id=current_user.default_account_id,
        account_grants=current_user.account_grants,
        accessible_accounts=accessible_accounts,
    )


@router.get("/my-accounts")
async def get_my_accounts(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[UserContext, Depends(get_current_user_context)],
) -> MyAccountsResponse:
    raw_accounts = await broker_account_service.list_accessible_accounts_for_context(
        session,
        current_user,
    )
    accounts = [AccessibleAccountView.model_validate(item) for item in raw_accounts]
    return MyAccountsResponse(
        accounts=accounts,
        accessible_account_ids=current_user.accessible_account_ids,
        default_account_id=current_user.default_account_id,
        account_grants=current_user.account_grants,
    )


@router.get("/permissions")
async def get_permissions(
    current_user: Annotated[UserContext, Depends(get_current_user_context)],
) -> AuthPermissionsResponse:
    return AuthPermissionsResponse(
        role=current_user.role,
        permissions=sorted(current_user.permissions),
        permissions_version=current_user.permissions_version,
    )


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[UserContext, Depends(get_current_user_context)],
) -> ChangePasswordResponse:
    if not settings.RBAC_V1121_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Password change endpoint is available only when "
                "RBAC_V1121 is enabled"
            ),
        )
    try:
        updated_user = await rbac_service.change_password(
            session,
            username=current_user.username,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return ChangePasswordResponse(
        user=AuthUserView(
            id=updated_user.user_id,
            username=updated_user.username,
            display_name=updated_user.display_name,
            role=updated_user.role,
            permissions=sorted(updated_user.permissions),
            permissions_version=updated_user.permissions_version,
            status=updated_user.status,
            is_system_seed=updated_user.is_system_seed,
            must_change_password=updated_user.must_change_password,
            feature_flags=_feature_flags_payload(),
            accessible_account_ids=updated_user.accessible_account_ids,
            default_account_id=updated_user.default_account_id,
            account_grants=updated_user.account_grants,
        )
    )
