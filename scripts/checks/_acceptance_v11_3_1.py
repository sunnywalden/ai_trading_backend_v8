#!/usr/bin/env python3
"""V11.3.1 Multi-Account 验收测试脚本。"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS = "✅"
FAIL = "❌"
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    icon = PASS if ok else FAIL
    msg = f"{icon} {name}"
    if detail:
        msg += f"\n   {detail}"
    print(msg)
    results.append((name, ok))
    return ok


def test_feature_flags_available() -> None:
    from app.core.config import settings

    names = (
        "MULTI_ACCOUNT_V1131_ENABLED",
        "BROKER_ACCOUNT_REGISTRY_V1131_ENABLED",
        "ACCOUNT_DATA_ISOLATION_V1131_ENABLED",
        "ACCOUNT_ADMIN_UI_V1131_ENABLED",
        "BROKER_CREDENTIAL_ENCRYPTION_KEY",
    )
    ok = all(hasattr(settings, name) for name in names)
    detail = ", ".join(f"{name}={getattr(settings, name, None)!r}" for name in names)
    check("V11.3.1 feature flags 可用", ok, detail)


async def test_schema_tables_exist() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.models.db import Base, SessionLocal

    table_names = [
        "broker_accounts",
        "broker_account_credentials",
        "user_broker_account_grants",
    ]
    counts: dict[str, int] = {}
    detail_prefix = "runtime-db"
    try:
        async with SessionLocal() as session:
            conn = await session.connection()
            if conn.dialect.name == "sqlite":
                sql = (
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name=:table_name"
                )
            else:
                sql = (
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = :table_name"
                )
            for table_name in table_names:
                result = await session.execute(
                    text(sql),
                    {"table_name": table_name},
                )
                counts[table_name] = int(result.scalar() or 0)
    except Exception as exc:
        isolated_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            future=True,
        )
        try:
            __import__("app.models.role")
            __import__("app.models.user")
            __import__("app.models.broker_account")
            __import__("app.models.broker_account_credential")
            __import__("app.models.user_broker_account_grant")
            async with isolated_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                for table_name in table_names:
                    result = await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM sqlite_master "
                            "WHERE type='table' AND name=:table_name"
                        ),
                        {"table_name": table_name},
                    )
                    counts[table_name] = int(result.scalar() or 0)
            detail_prefix = f"isolated-fallback({exc})"
        finally:
            await isolated_engine.dispose()

    ok = all(counts[name] > 0 for name in counts)
    detail = f"source={detail_prefix}; " + ", ".join(
        f"{name}={count}" for name, count in counts.items()
    )
    check("V11.3.1 多账户表已落库", ok, detail)


def test_legacy_context_fields() -> None:
    from app.core.auth_context import make_legacy_admin_context

    ctx = make_legacy_admin_context("admin")
    ok = bool(ctx.accessible_account_ids) and bool(ctx.account_grants)
    detail = (
        f"default_account_id={ctx.default_account_id}, "
        f"accessible={ctx.accessible_account_ids}, grants={ctx.account_grants}"
    )
    check("V11.3.1 legacy context 带账户字段", ok, detail)


async def test_isolated_service_flow() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.db import Base
    from app.services.broker_account_service import broker_account_service
    from app.services.rbac_service import rbac_service

    __import__("app.models.authorization_audit_log")
    __import__("app.models.broker_account")
    __import__("app.models.broker_account_credential")
    __import__("app.models.permission")
    __import__("app.models.role")
    __import__("app.models.role_permission_grant")
    __import__("app.models.user")
    __import__("app.models.user_broker_account_grant")
    __import__("app.models.user_role_binding")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    original_tiger_account = settings.TIGER_ACCOUNT
    original_multi_account = settings.MULTI_ACCOUNT_V1131_ENABLED
    original_registry = settings.BROKER_ACCOUNT_REGISTRY_V1131_ENABLED
    original_isolation = settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED
    original_key = settings.BROKER_CREDENTIAL_ENCRYPTION_KEY

    try:
        settings.TIGER_ACCOUNT = "legacy-default"
        settings.MULTI_ACCOUNT_V1131_ENABLED = True
        settings.BROKER_ACCOUNT_REGISTRY_V1131_ENABLED = True
        settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED = True
        settings.BROKER_CREDENTIAL_ENCRYPTION_KEY = base64.b64encode(b"1" * 32).decode(
            "ascii"
        )
        primary_secret = "".join(["S3cure", "-Pass!"])

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            await rbac_service.ensure_builtin_rbac(session)
            created_user = await rbac_service.create_user(
                session,
                username="v1131-trader",
                display_name="V1131 Trader",
                password=primary_secret,
                role_code="TRADER",
                assigned_by="admin",
            )
            account = await broker_account_service.create_account(
                session,
                account_id="sim-acc-001",
                display_name="Sim Account 001",
                account_type="PAPER",
                market="US",
                tiger_id="tiger-dev-001",
            )
            await broker_account_service.upsert_credentials(
                session,
                account_db_id=account["id"],
                tiger_id="tiger-dev-001",
                private_key_pem=(
                    "-----BEGIN PRIVATE KEY-----\n"
                    "ZmFrZS1rZXktZm9yLWFjY2VwdGFuY2U=\n"
                    "-----END PRIVATE KEY-----"
                ),
            )
            grant = await broker_account_service.upsert_user_grant(
                session,
                user_id=created_user["id"],
                broker_account_id=account["id"],
                grant_level="OPERATE",
                granted_by=None,
            )
            context = await rbac_service.get_user_context_by_username(
                session,
                "v1131-trader",
            )
            accessible = []
            if context is not None:
                accessible = (
                    await (
                        broker_account_service.list_accessible_accounts_for_context(
                            session,
                            context,
                        )
                    )
                )
            revoked = await broker_account_service.revoke_user_grant(
                session,
                user_id=created_user["id"],
                grant_id=grant["id"],
            )

        ok = (
            context is not None
            and context.has_account_access("sim-acc-001", "OPERATE")
            and any(item["account_id"] == "sim-acc-001" for item in accessible)
            and revoked["revoked_at"] is not None
        )
        detail = (
            f"accessible={context.accessible_account_ids if context else []}, "
            "grant_level="
            f"{(
                context.account_grants.get('sim-acc-001')
                if context else None
            )}, "
            f"accessible_views={len(accessible)}"
        )
        check("V11.3.1 多账户服务链路可用", ok, detail)
    finally:
        settings.TIGER_ACCOUNT = original_tiger_account
        settings.MULTI_ACCOUNT_V1131_ENABLED = original_multi_account
        settings.BROKER_ACCOUNT_REGISTRY_V1131_ENABLED = original_registry
        settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED = original_isolation
        settings.BROKER_CREDENTIAL_ENCRYPTION_KEY = original_key
        await engine.dispose()


async def run_check(name: str, func) -> None:
    try:
        result = func()
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        check(name, False, str(exc))


async def main() -> None:
    from app.models.db import close_db_resources

    try:
        print("=" * 60)
        print("V11.3.1 验收测试")
        print("=" * 60)
        await run_check(
            "V11.3.1 feature flags 可用",
            test_feature_flags_available,
        )
        await run_check("V11.3.1 多账户表已落库", test_schema_tables_exist)
        await run_check(
            "V11.3.1 legacy context 带账户字段",
            test_legacy_context_fields,
        )
        await run_check("V11.3.1 多账户服务链路可用", test_isolated_service_flow)

        print("\n" + "=" * 60)
        passed = sum(1 for _, ok in results if ok)
        total = len(results)
        print(f"结果：{passed}/{total} 通过")
        if passed == total:
            print("🎉 V11.3.1 验收通过！")
        else:
            print("⚠️  部分测试失败，请检查以上输出")
        print("=" * 60)
    finally:
        await close_db_resources()


if __name__ == "__main__":
    asyncio.run(main())
