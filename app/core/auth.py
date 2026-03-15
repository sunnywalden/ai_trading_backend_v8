from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from app.core.auth_context import UserContext, make_legacy_admin_context
from app.core.config import settings
from app.models.db import SessionLocal
from app.services.rbac_service import rbac_service

# OAuth2 token endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")

ALGORITHM = "HS256"


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


def _user_to_token_payload(user: UserContext) -> dict:
    return {
        "sub": user.username,
        "uid": user.user_id,
        "role": user.role,
        "display_name": user.display_name,
        "permissions": sorted(user.permissions),
        "permissions_version": user.permissions_version,
        "status": user.status,
        "must_change_password": user.must_change_password,
        "accessible_account_ids": user.accessible_account_ids,
        "default_account_id": user.default_account_id,
        "account_grants": user.account_grants,
    }


def _user_to_response_payload(user: UserContext) -> dict:
    return {
        "id": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "permissions": sorted(user.permissions),
        "permissions_version": user.permissions_version,
        "status": user.status,
        "is_system_seed": user.is_system_seed,
        "must_change_password": user.must_change_password,
        "feature_flags": _feature_flags_payload(),
        "accessible_account_ids": user.accessible_account_ids,
        "default_account_id": user.default_account_id,
        "account_grants": user.account_grants,
    }


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return encoded_jwt


async def authenticate_user(
    username: str,
    password: str,
) -> UserContext | None:
    if settings.RBAC_V1121_ENABLED:
        try:
            async with SessionLocal() as session:
                context = await rbac_service.authenticate_user(
                    session, username, password
                )
                if context is not None:
                    return context
        except Exception:
            pass

    if username != settings.ADMIN_USERNAME:
        return None
    configured_password = settings.ADMIN_PASSWORD
    if not configured_password:
        return None
    if not compare_digest(password, configured_password):
        return None
    return make_legacy_admin_context(username)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    return (await get_current_user_context(token)).username


async def get_current_user_context(
    token: str = Depends(oauth2_scheme),
) -> UserContext:
    if not settings.AUTH_ENABLED:
        return make_legacy_admin_context("anonymous")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    if settings.RBAC_V1121_ENABLED:
        try:
            async with SessionLocal() as session:
                context = await rbac_service.get_user_context_by_username(
                    session, username
                )
            if context is not None:
                return context
        except Exception:
            pass

    if username == settings.ADMIN_USERNAME:
        return make_legacy_admin_context(username)
    raise credentials_exception


async def login_for_access_token(form_data: OAuth2PasswordRequestForm) -> dict:
    if not settings.AUTH_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="Authentication is disabled",
        )

    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
        )

    access_token = create_access_token(data=_user_to_token_payload(user))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": _user_to_response_payload(user),
    }
