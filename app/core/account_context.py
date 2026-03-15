from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.auth import get_current_user_context
from app.core.auth_context import UserContext
from app.core.authz import _audit_denial
from app.core.config import settings

ACCOUNT_ACCESS_DENIED = "Account access denied"


async def get_current_account_id(
    request: Request,
    current_user: Annotated[UserContext, Depends(get_current_user_context)],
) -> str:
    if not settings.MULTI_ACCOUNT_V1131_ENABLED:
        return settings.TIGER_ACCOUNT

    requested_account_id = (
        request.headers.get("X-Account-ID")
        or request.query_params.get("account_id")
        or current_user.default_account_id
        or settings.TIGER_ACCOUNT
    )
    requested_account_id = str(requested_account_id or settings.TIGER_ACCOUNT).strip()

    if not settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED:
        return current_user.default_account_id or settings.TIGER_ACCOUNT

    if current_user.has_account_access(requested_account_id, "VIEW"):
        return requested_account_id

    await _audit_denial(
        current_user,
        resource="account",
        action="view",
        reason=ACCOUNT_ACCESS_DENIED,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ACCOUNT_ACCESS_DENIED,
    )


def require_account_access(min_level: str = "VIEW"):
    async def dependency(
        account_id: Annotated[str, Depends(get_current_account_id)],
        current_user: Annotated[
            UserContext,
            Depends(get_current_user_context),
        ],
    ) -> str:
        if not settings.MULTI_ACCOUNT_V1131_ENABLED:
            return settings.TIGER_ACCOUNT
        if not settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED:
            return current_user.default_account_id or settings.TIGER_ACCOUNT
        if current_user.has_account_access(account_id, min_level):
            return account_id

        await _audit_denial(
            current_user,
            resource="account",
            action=min_level.lower(),
            reason=ACCOUNT_ACCESS_DENIED,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ACCOUNT_ACCESS_DENIED,
        )

    return dependency
