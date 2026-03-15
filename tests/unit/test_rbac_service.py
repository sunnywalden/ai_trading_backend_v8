from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    authorization_audit_log,
    permission,
    role,
    role_permission_grant,
    user,
    user_role_binding,
)
from app.models.db import Base
from app.services.rbac_service import rbac_service

_REGISTERED_MODELS = (
    authorization_audit_log,
    permission,
    role,
    role_permission_grant,
    user,
    user_role_binding,
)

PRIMARY_SECRET = "".join(["S3cure", "-Pass!"])
ROTATED_SECRET = "".join(["N3wer", "-Pass!"])


@pytest.mark.asyncio
async def test_password_hash_roundtrip():
    password_hash = rbac_service.hash_password(PRIMARY_SECRET)

    assert password_hash.startswith("pbkdf2_sha256$")
    assert rbac_service.verify_password(PRIMARY_SECRET, password_hash) is True
    assert rbac_service.verify_password("wrong-pass", password_hash) is False


@pytest.mark.asyncio
async def test_create_user_and_authenticate_with_builtin_roles():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await rbac_service.ensure_builtin_rbac(session)
        created = await rbac_service.create_user(
            session,
            username="researcher01",
            display_name="Researcher 01",
            password=PRIMARY_SECRET,
            role_code="RESEARCHER",
            assigned_by="admin",
        )
        context = await rbac_service.authenticate_user(
            session,
            "researcher01",
            PRIMARY_SECRET,
        )

    await engine.dispose()

    assert created["default_role"] == "RESEARCHER"
    assert created["must_change_password"] is True
    assert context is not None
    assert context.username == "researcher01"
    assert context.role == "RESEARCHER"
    assert "research.home.read" in context.permissions
    assert "admin.home.read" not in context.permissions
    assert context.must_change_password is True


@pytest.mark.asyncio
async def test_role_assignment_updates_primary_role_and_permission_version():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await rbac_service.ensure_builtin_rbac(session)
        created = await rbac_service.create_user(
            session,
            username="ops-user",
            display_name="Ops User",
            password=PRIMARY_SECRET,
            role_code="RESEARCHER",
            assigned_by="admin",
        )
        updated = await rbac_service.update_user(
            session,
            user_id=created["id"],
            role_code="ADMINISTRATOR",
            assigned_by="admin",
        )
        context = await rbac_service.get_user_context_by_username(
            session,
            "ops-user",
        )

    await engine.dispose()

    assert updated["default_role"] == "ADMINISTRATOR"
    assert updated["permissions_version"] >= 2
    assert context is not None
    assert context.role == "ADMINISTRATOR"
    assert "*" in context.permissions


@pytest.mark.asyncio
async def test_change_password_clears_forced_reset_flag():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await rbac_service.ensure_builtin_rbac(session)
        created = await rbac_service.create_user(
            session,
            username="trader01",
            display_name="Trader 01",
            password=PRIMARY_SECRET,
            role_code="TRADER",
            assigned_by="admin",
        )
        assert created["must_change_password"] is True

        updated_context = await rbac_service.change_password(
            session,
            username="trader01",
            current_password=PRIMARY_SECRET,
            new_password=ROTATED_SECRET,
        )

    await engine.dispose()

    assert updated_context.must_change_password is False
    assert updated_context.permissions_version >= 2
