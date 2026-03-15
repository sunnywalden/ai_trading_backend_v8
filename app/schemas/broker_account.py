from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AccessibleAccountView(BaseModel):
    id: int | None = None
    account_id: str
    display_name: str | None = None
    account_type: str | None = None
    market: str | None = None
    grant_level: str = "VIEW"
    is_active: bool = True


class BrokerAccountView(BaseModel):
    id: int
    account_id: str
    display_name: str | None = None
    account_type: str = "LIVE"
    market: str = "US"
    tiger_id: str | None = None
    credential_ref: str | None = None
    credential_configured: bool = False
    key_fingerprint: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BrokerAccountListResponse(BaseModel):
    accounts: list[BrokerAccountView]


class BrokerAccountCreateRequest(BaseModel):
    account_id: str = Field(min_length=3, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    account_type: str = Field(default="LIVE", max_length=32)
    market: str = Field(default="US", max_length=16)
    tiger_id: str | None = Field(default=None, max_length=64)


class BrokerAccountUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    account_type: str | None = Field(default=None, max_length=32)
    market: str | None = Field(default=None, max_length=16)
    tiger_id: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None


class BrokerAccountCredentialUpsertRequest(BaseModel):
    tiger_id: str = Field(min_length=1, max_length=64)
    private_key_pem: str = Field(min_length=32)


class UserBrokerAccountGrantView(BaseModel):
    id: int
    user_id: int
    broker_account_id: int
    account_id: str
    display_name: str | None = None
    grant_level: str
    is_active: bool = True
    granted_at: datetime | None = None
    revoked_at: datetime | None = None


class UserBrokerAccountGrantListResponse(BaseModel):
    grants: list[UserBrokerAccountGrantView]


class UserBrokerAccountGrantCreateRequest(BaseModel):
    broker_account_id: int
    grant_level: str = Field(pattern="^(VIEW|ANALYZE|OPERATE|ADMIN)$")


class UserBrokerAccountGrantUpdateRequest(BaseModel):
    grant_level: str = Field(pattern="^(VIEW|ANALYZE|OPERATE|ADMIN)$")


class MyAccountsResponse(BaseModel):
    accounts: list[AccessibleAccountView]
    accessible_account_ids: list[str] = Field(default_factory=list)
    default_account_id: str | None = None
    account_grants: dict[str, str] = Field(default_factory=dict)
