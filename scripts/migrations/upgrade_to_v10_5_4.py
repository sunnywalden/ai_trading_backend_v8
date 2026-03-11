#!/usr/bin/env python3
"""upgrade_to_v10_5_4.py — V10.5.4 数据库迁移脚本。

差异对比（v10.5.3 → v10.5.4）：

      v10.5.4（本脚本）—— Signal Pipeline Integrity &
      Control-Plane Hardening
      ────────────────────────────────────────────────────────────────
      1. trading_signals.signal_origin_mode
          真源区分字段
      2. ix_signals_account_origin_status /
          ix_signals_origin_generated
          查询索引
      3. strategies.auto_scan_enabled / auto_scan_priority
          自动扫描治理字段
      4. ix_strategies_active_auto_scan_rank
          自动扫描选择索引

用法：
  python scripts/migrations/upgrade_to_v10_5_4.py
  python scripts/migrations/upgrade_to_v10_5_4.py --check
  python scripts/migrations/upgrade_to_v10_5_4.py --rollback
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _venv_python_path() -> str:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    exe_name = "python.exe" if os.name == "nt" else "python"
    return os.path.join(ROOT, ".venv", scripts_dir, exe_name)


def _ensure_sqlalchemy_available() -> None:
    if importlib.util.find_spec("sqlalchemy") is not None:
        return

    try:
        venv_python = _venv_python_path()
        same_python = os.path.abspath(sys.executable) == os.path.abspath(
            venv_python
        )
        if os.path.exists(venv_python) and not same_python:
            os.execv(venv_python, [venv_python, *sys.argv])

        raise SystemExit(
            "sqlalchemy 未安装。请先激活 .venv，或使用 .venv\\Scripts\\python.exe 运行该脚本。"
        )
    except OSError as exc:
        raise SystemExit(f"无法切换到项目 .venv 解释器：{exc}") from exc


_ensure_sqlalchemy_available()

sys.path.insert(0, ROOT)

ADD_COLUMNS = [
    (
        "trading_signals",
        "signal_origin_mode",
        """
ALTER TABLE trading_signals
ADD COLUMN signal_origin_mode VARCHAR(16) NULL
COMMENT 'V10.5.4: REAL/SYNTHETIC/BACKFILL'
""",
    ),
    (
        "strategies",
        "auto_scan_enabled",
        """
ALTER TABLE strategies
ADD COLUMN auto_scan_enabled TINYINT(1) NOT NULL DEFAULT 1
COMMENT 'V10.5.4: 是否参与自动扫描'
""",
    ),
    (
        "strategies",
        "auto_scan_priority",
        """
ALTER TABLE strategies
ADD COLUMN auto_scan_priority INT NOT NULL DEFAULT 100
COMMENT 'V10.5.4: 自动扫描优先级，越高越优先'
""",
    ),
]

DROP_COLUMNS = [
    "ALTER TABLE strategies DROP COLUMN auto_scan_priority",
    "ALTER TABLE strategies DROP COLUMN auto_scan_enabled",
    "ALTER TABLE trading_signals DROP COLUMN signal_origin_mode",
]

CREATE_INDEXES = [
    (
        "trading_signals",
        "ix_signals_account_origin_status",
        (
            "CREATE INDEX ix_signals_account_origin_status ON trading_signals "
            "(account_id, signal_origin_mode, status)"
        ),
    ),
    (
        "trading_signals",
        "ix_signals_origin_generated",
        (
            "CREATE INDEX ix_signals_origin_generated ON trading_signals "
            "(signal_origin_mode, generated_at)"
        ),
    ),
    (
        "strategies",
        "ix_strategies_active_auto_scan_rank",
        (
            "CREATE INDEX ix_strategies_active_auto_scan_rank ON strategies "
            "(is_active, auto_scan_enabled, auto_scan_priority, last_run_at)"
        ),
    ),
]

DROP_INDEXES = [
    "DROP INDEX ix_strategies_active_auto_scan_rank ON strategies",
    "DROP INDEX ix_signals_account_origin_status ON trading_signals",
    "DROP INDEX ix_signals_origin_generated ON trading_signals",
]


async def _column_exists(conn, table_name: str, column_name: str) -> bool:
    from sqlalchemy import text

    res = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = :table_name "
            "AND column_name = :column_name"
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
        },
    )
    return bool(res.scalar())


async def _index_exists(
    conn,
    table_name: str,
    index_name: str,
) -> bool:
    from sqlalchemy import text

    res = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() "
            "AND table_name = :table_name "
            "AND index_name = :index_name"
        ),
        {
            "table_name": table_name,
            "index_name": index_name,
        },
    )
    return bool(res.scalar())


async def run_upgrade() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            for table_name, column_name, sql in ADD_COLUMNS:
                if not await _column_exists(conn, table_name, column_name):
                    print(f"[upgrade] Adding {table_name}.{column_name}...")
                    await conn.execute(text(sql))
                else:
                    print(
                        f"[upgrade] {table_name}.{column_name} already exists"
                    )

            for table_name, index_name, sql in CREATE_INDEXES:
                if not await _index_exists(conn, table_name, index_name):
                    print(f"[upgrade] Creating index {index_name}...")
                    await conn.execute(text(sql))
                else:
                    print(f"[upgrade] Index {index_name} already exists")

            print("[upgrade] ✓ V10.5.4 migration complete")
    finally:
        await engine.dispose()


async def run_rollback() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            for sql in DROP_INDEXES:
                try:
                    await conn.execute(text(sql))
                except Exception:
                    pass

            for sql in DROP_COLUMNS:
                try:
                    await conn.execute(text(sql))
                except Exception:
                    pass
            print("[rollback] ✓ V10.5.4 rollback complete")
    finally:
        await engine.dispose()


async def run_check() -> None:
    from app.models.db import engine

    try:
        async with engine.connect() as conn:
            for table_name, column_name, _sql in ADD_COLUMNS:
                exists = await _column_exists(conn, table_name, column_name)
                print(f"[check] {table_name}.{column_name}={exists}")
            for table_name, index_name, _sql in CREATE_INDEXES:
                exists = await _index_exists(conn, table_name, index_name)
                print(f"[check] {index_name}={exists}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="V10.5.4 DB migration")
    parser.add_argument("--rollback", action="store_true", help="Roll back")
    parser.add_argument("--check", action="store_true", help="Check status")
    args = parser.parse_args()

    if args.rollback:
        asyncio.run(run_rollback())
    elif args.check:
        asyncio.run(run_check())
    else:
        asyncio.run(run_upgrade())


if __name__ == "__main__":
    main()
