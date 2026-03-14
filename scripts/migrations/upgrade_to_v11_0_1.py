#!/usr/bin/env python3
"""upgrade_to_v11_0_1.py — V11.0.1 数据库迁移脚本。

差异对比（v10.5.4 → v11.0.1）：

    V11.0.1 — Capital Intelligence & Self-Perception Foundation
    ─────────────────────────────────────────────────────────────
    1. 新建表 meta_state_snapshots
       系统元状态快照（M2 自知画像）

    2. 新建表 improvement_candidates
       M3 改进候选条目

用法（需先激活 .venv 环境）：
  python scripts/migrations/upgrade_to_v11_0_1.py
  python scripts/migrations/upgrade_to_v11_0_1.py --check
  python scripts/migrations/upgrade_to_v11_0_1.py --rollback
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
    try:
        venv_python = _venv_python_path()
        same_python = os.path.abspath(sys.executable) == os.path.abspath(venv_python)
        if os.path.exists(venv_python) and not same_python:
            os.execv(venv_python, [venv_python, *sys.argv])
        raise SystemExit(
            "sqlalchemy 未安装。请先激活 .venv 或使用 "
            ".venv\\Scripts\\python.exe 运行该脚本。"
        )
    except OSError as exc:
        raise SystemExit(f"无法切换到项目 .venv 解释器：{exc}") from exc


_ensure_sqlalchemy_available()
sys.path.insert(0, ROOT)

# ──────────────────────────────────────────────────────────────────────────
# DDL 定义
# ──────────────────────────────────────────────────────────────────────────

CREATE_TABLES = [
    (
        "meta_state_snapshots",
        """
CREATE TABLE IF NOT EXISTS meta_state_snapshots (
    id                      INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    snapshot_id             VARCHAR(64) NOT NULL,
    account_id              VARCHAR(64) NOT NULL,
    generated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    throttled_signals_count INT NOT NULL DEFAULT 0,
    false_hold_count        INT NOT NULL DEFAULT 0,
    total_blocked_signals   INT NOT NULL DEFAULT 0,
    idle_cash_ratio         FLOAT NULL,
    gross_exposure_pct      FLOAT NULL,
    snapshot_json           JSON NULL,
    notes                   TEXT NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_meta_state_snapshot_id (snapshot_id),
    INDEX ix_meta_state_snapshots_account (account_id),
    INDEX ix_meta_state_snapshots_account_generated (account_id, generated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='V11.0.1: 系统元状态快照'
""",
    ),
    (
        "improvement_candidates",
        """
CREATE TABLE IF NOT EXISTS improvement_candidates (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account_id      VARCHAR(64) NOT NULL,
    candidate_type  VARCHAR(64) NOT NULL DEFAULT 'parameter_tuning',
    target_module   VARCHAR(128) NOT NULL,
    target_param    VARCHAR(128) NOT NULL,
    current_value   FLOAT NULL,
    suggested_value FLOAT NULL,
    confidence      FLOAT NOT NULL DEFAULT 0.0,
    trigger_source  VARCHAR(64) NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',
    evidence_summary TEXT NULL,
    expected_impact TEXT NULL,
    validation_plan TEXT NULL,
    reviewed_at     DATETIME NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_improvement_candidates_account_status (account_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='V11.0.1: M3改进候选条目'
""",
    ),
]

ADD_COLUMNS = [
    (
        "improvement_candidates",
        "candidate_type",
        """
ALTER TABLE improvement_candidates
ADD COLUMN candidate_type VARCHAR(64) NOT NULL DEFAULT 'parameter_tuning'
COMMENT 'V11.0.1: 改进类型'
""",
    ),
    (
        "improvement_candidates",
        "expected_impact",
        """
ALTER TABLE improvement_candidates
ADD COLUMN expected_impact TEXT NULL
COMMENT 'V11.0.1: 预期影响'
""",
    ),
    (
        "improvement_candidates",
        "validation_plan",
        """
ALTER TABLE improvement_candidates
ADD COLUMN validation_plan TEXT NULL
COMMENT 'V11.0.1: 验证计划'
""",
    ),
    (
        "improvement_candidates",
        "reviewed_at",
        """
ALTER TABLE improvement_candidates
ADD COLUMN reviewed_at DATETIME NULL
COMMENT 'V11.0.1: 审核时间'
""",
    ),
    (
        "strategies",
        "governance_stage",
        """
ALTER TABLE strategies
ADD COLUMN governance_stage VARCHAR(32) NULL
COMMENT 'V11.0.1: DISCOVERY/PAPER/SHADOW_LIVE/CHALLENGER/PRODUCTION/LIMITED/RETIRED'
""",
    ),
    (
        "strategies",
        "governance_note",
        """
ALTER TABLE strategies
ADD COLUMN governance_note TEXT NULL
COMMENT 'V11.0.1: 治理说明/回滚备注'
""",
    ),
]

DROP_TABLES_ROLLBACK = [
    "DROP TABLE IF EXISTS improvement_candidates",
    "DROP TABLE IF EXISTS meta_state_snapshots",
]

DROP_COLUMNS_ROLLBACK = [
    "ALTER TABLE strategies DROP COLUMN governance_note",
    "ALTER TABLE strategies DROP COLUMN governance_stage",
]


# ──────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────


async def _table_exists(conn, table_name: str) -> bool:
    from sqlalchemy import text

    res = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() "
            "AND table_name = :table_name"
        ),
        {"table_name": table_name},
    )
    return bool(res.scalar())


async def _column_exists(conn, table_name: str, column_name: str) -> bool:
    from sqlalchemy import text

    res = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = :table_name "
            "AND column_name = :column_name"
        ),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(res.scalar())


# ──────────────────────────────────────────────────────────────────────────
# Upgrade / rollback
# ──────────────────────────────────────────────────────────────────────────


async def run_check() -> None:
    from app.models.db import engine

    try:
        async with engine.connect() as conn:
            for table_name, _ in CREATE_TABLES:
                exists = await _table_exists(conn, table_name)
                status = "✓ exists" if exists else "✗ missing"
                print(f"[check] {table_name}: {status}")
    finally:
        await engine.dispose()


async def run_upgrade() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            for table_name, ddl in CREATE_TABLES:
                if not await _table_exists(conn, table_name):
                    print(f"[upgrade] Creating table {table_name}...")
                    await conn.execute(text(ddl))
                    print(f"[upgrade] ✓ {table_name} created")
                else:
                    print(f"[upgrade] {table_name} already exists")

            for table_name, column_name, ddl in ADD_COLUMNS:
                if not await _column_exists(conn, table_name, column_name):
                    print(f"[upgrade] Adding {table_name}.{column_name}...")
                    await conn.execute(text(ddl))
                else:
                    print(f"[upgrade] {table_name}.{column_name} already exists")
        print("[upgrade] ✓ V11.0.1 migration complete")
    finally:
        await engine.dispose()


async def run_rollback() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            for sql in DROP_COLUMNS_ROLLBACK:
                try:
                    await conn.execute(text(sql))
                except Exception:
                    pass
            for sql in DROP_TABLES_ROLLBACK:
                table = sql.split()[-1]
                print(f"[rollback] Dropping {table}...")
                await conn.execute(text(sql))
        print("[rollback] ✓ V11.0.1 rollback complete")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="V11.0.1 数据库迁移脚本")
    parser.add_argument("--check", action="store_true", help="仅检查表是否存在")
    parser.add_argument("--rollback", action="store_true", help="回滚（删除新建表）")
    args = parser.parse_args()

    if args.check:
        asyncio.run(run_check())
    elif args.rollback:
        asyncio.run(run_rollback())
    else:
        asyncio.run(run_upgrade())


if __name__ == "__main__":
    main()
