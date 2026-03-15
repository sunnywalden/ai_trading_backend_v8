#!/usr/bin/env python3
"""upgrade_to_v11_3_1.py — V11.3.1 multi-account schema migration.

用法：
  python scripts/migrations/upgrade_to_v11_3_1.py
  python scripts/migrations/upgrade_to_v11_3_1.py --check
  python scripts/migrations/upgrade_to_v11_3_1.py --rollback
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _venv_python_path() -> str:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    exe_name = "python.exe" if os.name == "nt" else "python"
    return os.path.join(ROOT, ".venv", scripts_dir, exe_name)


def _ensure_sqlalchemy_available() -> None:
    if importlib.util.find_spec("sqlalchemy") is not None:
        return
    venv_python = _venv_python_path()
    same_python = os.path.abspath(sys.executable) == os.path.abspath(venv_python)
    if os.path.exists(venv_python) and not same_python:
        os.execv(venv_python, [venv_python, *sys.argv])
    raise SystemExit(
        "sqlalchemy 未安装。请先激活 .venv 或使用 .venv\\Scripts\\python.exe 运行该脚本。"
    )


_ensure_sqlalchemy_available()
sys.path.insert(0, ROOT)

TABLES = [
    "broker_accounts",
    "broker_account_credentials",
    "user_broker_account_grants",
]

MODEL_MODULES = (
    "app.models.authorization_audit_log",
    "app.models.permission",
    "app.models.role",
    "app.models.role_permission_grant",
    "app.models.user",
    "app.models.broker_account",
    "app.models.broker_account_credential",
    "app.models.user_broker_account_grant",
    "app.models.user_role_binding",
)


def _load_model_modules() -> None:
    for module_name in MODEL_MODULES:
        importlib.import_module(module_name)


def _fallback_grant_for_role(role_code: str | None) -> str:
    normalized = (role_code or "").upper()
    if normalized == "ADMINISTRATOR":
        return "ADMIN"
    if normalized == "TRADER":
        return "OPERATE"
    if normalized in {"RESEARCHER", "SUPERVISOR"}:
        return "ANALYZE"
    return "VIEW"


async def _table_exists(conn, table_name: str) -> bool:
    from sqlalchemy import text

    if conn.dialect.name == "sqlite":
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name=:table_name"
            ),
            {"table_name": table_name},
        )
        return bool(result.scalar())

    result = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = :table_name"
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


async def run_check() -> None:
    from sqlalchemy import select

    _load_model_modules()

    from app.models.broker_account import BrokerAccount
    from app.models.db import engine

    try:
        async with engine.connect() as conn:
            for table_name in TABLES:
                exists = await _table_exists(conn, table_name)
                status_label = "✓ exists" if exists else "✗ missing"
                print(f"[check] {table_name}: {status_label}")
        from app.models.db import SessionLocal

        async with SessionLocal() as session:
            default_account = (
                await session.execute(
                    select(BrokerAccount).order_by(BrokerAccount.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if default_account is None:
                print("[check] broker_accounts seed: ✗ no account rows found")
            else:
                print(
                    "[check] broker_accounts seed: "
                    f"✓ found account_id={default_account.account_id}"
                )
    finally:
        await engine.dispose()


async def _backfill_default_account_and_grants() -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.config import settings
    from app.models.broker_account import BrokerAccount
    from app.models.db import SessionLocal
    from app.models.user import User
    from app.models.user_broker_account_grant import UserBrokerAccountGrant

    default_account_id = settings.TIGER_ACCOUNT or "demo-account"

    async with SessionLocal() as session:
        account = (
            await session.execute(
                select(BrokerAccount).where(
                    BrokerAccount.account_id == default_account_id
                )
            )
        ).scalar_one_or_none()
        created_account = False
        if account is None:
            account = BrokerAccount(
                account_id=default_account_id,
                display_name="Default Tiger Account",
                account_type="LIVE",
                market="US",
                tiger_id=settings.TIGER_ID,
                credential_ref=(
                    "legacy:tiger_singleton"
                    if settings.TIGER_PRIVATE_KEY_PATH
                    else None
                ),
                is_active=True,
            )
            session.add(account)
            await session.flush()
            created_account = True

        users = list(
            (
                await session.execute(
                    select(User).options(
                        selectinload(User.default_role),
                        selectinload(User.account_grants),
                    )
                )
            )
            .scalars()
            .all()
        )

        created_grants = 0
        for user in users:
            has_active_grant = any(
                grant.is_active and grant.revoked_at is None
                for grant in user.account_grants
            )
            if has_active_grant:
                continue
            session.add(
                UserBrokerAccountGrant(
                    user_id=user.id,
                    broker_account_id=account.id,
                    grant_level=_fallback_grant_for_role(
                        (
                            user.default_role.code
                            if user.default_role is not None
                            else None
                        )
                    ),
                    granted_by=None,
                    is_active=True,
                )
            )
            user.permissions_version = int(user.permissions_version or 0) + 1
            created_grants += 1

        await session.commit()
        print(
            "[upgrade] backfill summary: "
            "default_account_created="
            f"{created_account}, grants_created={created_grants}"
        )


async def run_upgrade() -> None:
    from app.models.db import Base, engine

    _load_model_modules()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await _backfill_default_account_and_grants()
        print("[upgrade] ✓ V11.3.1 migration complete")
    finally:
        await engine.dispose()


async def run_rollback() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    drop_sql = [
        "DROP TABLE IF EXISTS user_broker_account_grants",
        "DROP TABLE IF EXISTS broker_account_credentials",
        "DROP TABLE IF EXISTS broker_accounts",
    ]

    try:
        async with engine.begin() as conn:
            for sql in drop_sql:
                await conn.execute(text(sql))
        print("[rollback] ✓ V11.3.1 rollback complete")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="V11.3.1 multi-account migration")
    parser.add_argument("--check", action="store_true", help="仅检查表是否存在")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="回滚 V11.3.1 多账户表",
    )
    args = parser.parse_args()

    if args.check:
        asyncio.run(run_check())
    elif args.rollback:
        asyncio.run(run_rollback())
    else:
        asyncio.run(run_upgrade())


if __name__ == "__main__":
    main()
