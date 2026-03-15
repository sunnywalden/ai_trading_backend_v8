#!/usr/bin/env python3
"""upgrade_to_v11_2_1.py — V11.2.1 RBAC schema migration.

用法：
  python scripts/migrations/upgrade_to_v11_2_1.py
  python scripts/migrations/upgrade_to_v11_2_1.py --check
  python scripts/migrations/upgrade_to_v11_2_1.py --rollback
"""
from __future__ import annotations

import argparse
import asyncio
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
    "roles",
    "permissions",
    "users",
    "user_role_bindings",
    "role_permission_grants",
    "authorization_audit_logs",
]


async def _table_exists(conn, table_name: str) -> bool:
    from sqlalchemy import text

    if conn.dialect.name == "sqlite":
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:table_name"
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


async def _column_exists(conn, table_name: str, column_name: str) -> bool:
    from sqlalchemy import text

    if conn.dialect.name == "sqlite":
        result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        return any(row[1] == column_name for row in result.fetchall())

    result = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :table_name "
            "AND column_name = :column_name"
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


async def _ensure_v1121_patch_columns(conn) -> None:
    from sqlalchemy import text

    if await _table_exists(conn, "users") and not await _column_exists(
        conn, "users", "must_change_password"
    ):
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"
            )
        )


async def run_check() -> None:
    from app.models.db import engine

    try:
        async with engine.connect() as conn:
            for table_name in TABLES:
                exists = await _table_exists(conn, table_name)
                print(f"[check] {table_name}: {'✓ exists' if exists else '✗ missing'}")
            if await _table_exists(conn, "users"):
                has_column = await _column_exists(conn, "users", "must_change_password")
                print(
                    "[check] users.must_change_password: "
                    f"{'✓ exists' if has_column else '✗ missing'}"
                )
    finally:
        await engine.dispose()


async def run_upgrade() -> None:
    from app.models import (
        authorization_audit_log,
        permission,  # noqa: F401
        role,
        role_permission_grant,
        user,
        user_role_binding,
    )
    from app.models.db import Base, SessionLocal, engine
    from app.services.rbac_service import rbac_service

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_v1121_patch_columns(conn)
        async with SessionLocal() as session:
            await rbac_service.ensure_builtin_rbac(session)
        print("[upgrade] ✓ V11.2.1 migration complete")
    finally:
        await engine.dispose()


async def run_rollback() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    drop_sql = [
        "DROP TABLE IF EXISTS authorization_audit_logs",
        "DROP TABLE IF EXISTS role_permission_grants",
        "DROP TABLE IF EXISTS user_role_bindings",
        "DROP TABLE IF EXISTS users",
        "DROP TABLE IF EXISTS permissions",
        "DROP TABLE IF EXISTS roles",
    ]

    try:
        async with engine.begin() as conn:
            for sql in drop_sql:
                await conn.execute(text(sql))
        print("[rollback] ✓ V11.2.1 rollback complete")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="V11.2.1 RBAC migration")
    parser.add_argument("--check", action="store_true", help="仅检查表是否存在")
    parser.add_argument("--rollback", action="store_true", help="回滚 RBAC 表")
    args = parser.parse_args()

    if args.check:
        asyncio.run(run_check())
    elif args.rollback:
        asyncio.run(run_rollback())
    else:
        asyncio.run(run_upgrade())


if __name__ == "__main__":
    main()
