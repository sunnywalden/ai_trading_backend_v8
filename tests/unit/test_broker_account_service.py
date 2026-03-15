from __future__ import annotations

import base64

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models import (
    authorization_audit_log,
    broker_account,
    broker_account_credential,
    permission,
    role,
    role_permission_grant,
    user,
    user_broker_account_grant,
    user_role_binding,
)
from app.models.db import Base
from app.services.broker_account_service import broker_account_service
from app.services.rbac_service import rbac_service

_REGISTERED_MODELS = (
    authorization_audit_log,
    broker_account,
    broker_account_credential,
    permission,
    role,
    role_permission_grant,
    user,
    user_broker_account_grant,
    user_role_binding,
)

PRIMARY_SECRET = "S3cure-Pass!"


@pytest.mark.asyncio
async def test_user_context_includes_account_grants_after_assignment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    original_tiger_account = settings.TIGER_ACCOUNT
    original_key = settings.BROKER_CREDENTIAL_ENCRYPTION_KEY

    try:
        settings.TIGER_ACCOUNT = "legacy-default"
        settings.BROKER_CREDENTIAL_ENCRYPTION_KEY = base64.b64encode(b"2" * 32).decode(
            "ascii"
        )

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            await rbac_service.ensure_builtin_rbac(session)
            created_user = await rbac_service.create_user(
                session,
                username="multi-trader",
                display_name="Multi Trader",
                password=PRIMARY_SECRET,
                role_code="TRADER",
                assigned_by="admin",
            )
            account = await broker_account_service.create_account(
                session,
                account_id="acc-101",
                display_name="Account 101",
                account_type="LIVE",
                market="US",
                tiger_id="dev-101",
            )
            await broker_account_service.upsert_credentials(
                session,
                account_db_id=account["id"],
                tiger_id="dev-101",
                private_key_pem=(
                    "-----BEGIN PRIVATE KEY-----\n"
                    "bXVsdGktYWNjb3VudC10ZXN0LWtleQ==\n"
                    "-----END PRIVATE KEY-----"
                ),
            )
            await broker_account_service.upsert_user_grant(
                session,
                user_id=created_user["id"],
                broker_account_id=account["id"],
                grant_level="OPERATE",
                granted_by=None,
            )
            context = await rbac_service.get_user_context_by_username(
                session,
                "multi-trader",
            )

        assert context is not None
        assert context.default_account_id == "acc-101"
        assert context.account_grants["acc-101"] == "OPERATE"
        assert "acc-101" in context.accessible_account_ids
        assert context.has_account_access("acc-101", "OPERATE") is True
        assert context.has_account_access("acc-101", "ADMIN") is False
    finally:
        settings.TIGER_ACCOUNT = original_tiger_account
        settings.BROKER_CREDENTIAL_ENCRYPTION_KEY = original_key
        await engine.dispose()


@pytest.mark.asyncio
async def test_revoke_user_grant_marks_timestamp_and_removes_active_access():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    original_tiger_account = settings.TIGER_ACCOUNT

    try:
        settings.TIGER_ACCOUNT = "legacy-default"

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            await rbac_service.ensure_builtin_rbac(session)
            created_user = await rbac_service.create_user(
                session,
                username="grant-user",
                display_name="Grant User",
                password=PRIMARY_SECRET,
                role_code="RESEARCHER",
                assigned_by="admin",
            )
            account = await broker_account_service.create_account(
                session,
                account_id="acc-202",
                display_name="Account 202",
                account_type="PAPER",
                market="US",
                tiger_id=None,
            )
            grant = await broker_account_service.upsert_user_grant(
                session,
                user_id=created_user["id"],
                broker_account_id=account["id"],
                grant_level="ANALYZE",
                granted_by=None,
            )
            revoked = await broker_account_service.revoke_user_grant(
                session,
                user_id=created_user["id"],
                grant_id=grant["id"],
            )
            context = await rbac_service.get_user_context_by_username(
                session,
                "grant-user",
            )

        assert revoked["revoked_at"] is not None
        assert context is not None
        assert "acc-202" not in context.account_grants
        assert context.has_account_access("acc-202", "VIEW") is False
    finally:
        settings.TIGER_ACCOUNT = original_tiger_account
        await engine.dispose()
