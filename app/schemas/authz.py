from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.broker_account import AccessibleAccountView


class AuthUserView(BaseModel):
    id: int | None = None
    username: str
    display_name: str | None = None
    role: str
    permissions: list[str] = Field(default_factory=list)
    permissions_version: int = 1
    status: str = "ACTIVE"
    is_system_seed: bool = False
    must_change_password: bool = False
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    accessible_account_ids: list[str] = Field(default_factory=list)
    default_account_id: str | None = None
    account_grants: dict[str, str] = Field(default_factory=dict)
    accessible_accounts: list[AccessibleAccountView] = Field(default_factory=list)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserView


class AuthPermissionsResponse(BaseModel):
    role: str
    permissions: list[str]
    permissions_version: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ChangePasswordResponse(BaseModel):
    status: str = "ok"
    user: AuthUserView


class AdminUserListItem(BaseModel):
    id: int
    username: str
    display_name: str
    status: str
    default_role: str
    permissions_version: int
    is_system_seed: bool
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime


class AdminUserListResponse(BaseModel):
    users: list[AdminUserListItem]


class AdminUserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role_code: str = Field(min_length=3, max_length=64)


class AdminUserUpdateRequest(BaseModel):
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    password: str | None = Field(default=None, min_length=8, max_length=256)
    status: str | None = Field(default=None, pattern="^(ACTIVE|DISABLED)$")
    role_code: str | None = Field(default=None, min_length=3, max_length=64)


class AdminUserRoleAssignRequest(BaseModel):
    role_code: str = Field(min_length=3, max_length=64)


class AdminRoleListItem(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    is_system_builtin: bool = False
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminRoleListResponse(BaseModel):
    roles: list[AdminRoleListItem]


class AdminRoleCreateRequest(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class AdminRoleUpdateRequest(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class AdminPermissionItem(BaseModel):
    id: int
    code: str
    resource: str
    action: str
    scope: str
    access_mode: str
    description: str | None = None


class AdminPermissionListResponse(BaseModel):
    permissions: list[AdminPermissionItem]


class AdminAuditLogItem(BaseModel):
    id: int
    username: str
    event_type: str
    resource: str
    action: str
    decision: str
    reason: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AdminAuditLogResponse(BaseModel):
    items: list[AdminAuditLogItem]
