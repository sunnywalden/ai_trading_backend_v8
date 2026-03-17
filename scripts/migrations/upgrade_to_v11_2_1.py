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
from importlib import import_module

from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_MODULES = (
    "app.models.authorization_audit_log",
    "app.models.permission",
    "app.models.role",
    "app.models.role_permission_grant",
    "app.models.user",
    "app.models.user_role_binding",
)


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


def _load_v1121_model_modules() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)


async def _table_exists(conn, table_name: str) -> bool:
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


async def _column_exists(conn, table_name: str, column_name: str) -> bool:
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
    if await _table_exists(conn, "users") and not await _column_exists(
        conn, "users", "must_change_password"
    ):
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN must_change_password "
                "BOOLEAN NOT NULL DEFAULT 0"
            )
        )


async def _ensure_role_record(conn, code: str, payload: dict[str, str]) -> int:
    result = await conn.execute(
        text("SELECT id FROM roles WHERE code = :code"),
        {"code": code},
    )
    role_id = result.scalar_one_or_none()

    params = {
        "code": code,
        "name": payload["name"],
        "description": payload["description"],
        "is_system_builtin": True,
    }
    if role_id is None:
        await conn.execute(
            text(
                "INSERT INTO roles "
                "(code, name, description, is_system_builtin) "
                "VALUES (:code, :name, :description, :is_system_builtin)"
            ),
            params,
        )
        result = await conn.execute(
            text("SELECT id FROM roles WHERE code = :code"),
            {"code": code},
        )
        role_id = result.scalar_one()
    else:
        await conn.execute(
            text(
                "UPDATE roles "
                "SET name = :name, description = :description, "
                "is_system_builtin = :is_system_builtin, "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :id"
            ),
            {**params, "id": role_id},
        )

    return int(role_id)


async def _ensure_permission_record(conn, payload: dict[str, str]) -> int:
    result = await conn.execute(
        text("SELECT id FROM permissions WHERE code = :code"),
        {"code": payload["code"]},
    )
    permission_id = result.scalar_one_or_none()

    params = {
        "code": payload["code"],
        "resource": payload["resource"],
        "action": payload["action"],
        "scope": payload["scope"],
        "access_mode": payload["access_mode"],
        "description": payload["description"],
    }
    if permission_id is None:
        await conn.execute(
            text(
                "INSERT INTO permissions "
                "(code, resource, action, scope, access_mode, description) "
                "VALUES "
                "(:code, :resource, :action, :scope, :access_mode, "
                ":description)"
            ),
            params,
        )
        result = await conn.execute(
            text("SELECT id FROM permissions WHERE code = :code"),
            {"code": payload["code"]},
        )
        permission_id = result.scalar_one()
    else:
        await conn.execute(
            text(
                "UPDATE permissions "
                "SET resource = :resource, action = :action, scope = :scope, "
                "access_mode = :access_mode, description = :description "
                "WHERE id = :id"
            ),
            {**params, "id": permission_id},
        )

    return int(permission_id)


async def _seed_builtin_rbac(conn) -> None:
    from app.services.rbac_service import (
        BUILTIN_PERMISSIONS,
        BUILTIN_ROLES,
        ROLE_PERMISSION_CODES,
    )

    role_ids = {
        code: await _ensure_role_record(conn, code, payload)
        for code, payload in BUILTIN_ROLES.items()
    }
    permission_ids = {
        payload["code"]: await _ensure_permission_record(conn, payload)
        for payload in BUILTIN_PERMISSIONS
    }

    result = await conn.execute(
        text("SELECT role_id, permission_id FROM role_permission_grants")
    )
    existing_grants = {
        (int(row.role_id), int(row.permission_id)) for row in result.fetchall()
    }

    for role_code, permission_codes in ROLE_PERMISSION_CODES.items():
        role_id = role_ids[role_code]
        for permission_code in permission_codes:
            permission_id = permission_ids[permission_code]
            grant_key = (role_id, permission_id)
            if grant_key in existing_grants:
                continue
            await conn.execute(
                text(
                    "INSERT INTO role_permission_grants "
                    "(role_id, permission_id, grant_scope) "
                    "VALUES (:role_id, :permission_id, :grant_scope)"
                ),
                {
                    "role_id": role_id,
                    "permission_id": permission_id,
                    "grant_scope": "global",
                },
            )
            existing_grants.add(grant_key)


async def run_check() -> None:
    _load_v1121_model_modules()
    from app.models.db import engine

    try:
        async with engine.connect() as conn:
            for table_name in TABLES:
                exists = await _table_exists(conn, table_name)
                status = "✓ exists" if exists else "✗ missing"
                print(f"[check] {table_name}: {status}")
            if await _table_exists(conn, "users"):
                has_column = await _column_exists(
                    conn,
                    "users",
                    "must_change_password",
                )
                print(
                    "[check] users.must_change_password: "
                    f"{'✓ exists' if has_column else '✗ missing'}"
                )
    finally:
        await engine.dispose()


async def run_upgrade() -> None:
    _load_v1121_model_modules()
    from app.models.db import Base, engine

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_v1121_patch_columns(conn)
            await _seed_builtin_rbac(conn)
        print("[upgrade] ✓ V11.2.1 migration complete")
    finally:
        await engine.dispose()


async def run_rollback() -> None:
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
