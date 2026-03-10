#!/usr/bin/env python3
"""upgrade_to_v10_5_3.py — V10.5.3 数据库迁移脚本。

差异对比（v10.5.2 → v10.5.3）：

  v10.5.3（本脚本）—— 收益控制闭环升级
  ──────────────────────────────────────────────────────
  1. execution_policy_profiles  执行策略长期反馈画像（Execution Closed Loop）

用法：
  python scripts/migrations/upgrade_to_v10_5_3.py
  python scripts/migrations/upgrade_to_v10_5_3.py --check
  python scripts/migrations/upgrade_to_v10_5_3.py --rollback
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
        raise SystemExit(
            f"无法切换到项目 .venv 解释器：{exc}"
        ) from exc


_ensure_sqlalchemy_available()

sys.path.insert(
    0,
    ROOT,
)

MYSQL_UP = "\n".join(
    [
        "CREATE TABLE IF NOT EXISTS execution_policy_profiles (",
        "    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',",
        "    account_id VARCHAR(64) NOT NULL COMMENT '账户 ID',",
        "    symbol VARCHAR(32) NOT NULL COMMENT '标的代码',",
        "    side VARCHAR(8) NOT NULL COMMENT 'BUY/SELL',",
        (
            "    urgency_bucket VARCHAR(16) NOT NULL "
            "COMMENT 'LOW/MEDIUM/HIGH/FORCED',"
        ),
        (
            "    algo_type VARCHAR(32) NOT NULL "
            "COMMENT 'LIMIT/MARKET/TWAP/VWAP',"
        ),
        "    sample_size INT NOT NULL DEFAULT 0 COMMENT '聚合样本数',",
        (
            "    avg_total_is_bps FLOAT NOT NULL DEFAULT 0 "
            "COMMENT '平均总 IS bps',"
        ),
        "    avg_fill_rate FLOAT NOT NULL DEFAULT 0 COMMENT '平均成交率',",
        (
            "    avg_quality_score FLOAT NOT NULL DEFAULT 0 "
            "COMMENT '平均执行质量分',"
        ),
        (
            "    last_total_is_bps FLOAT NOT NULL DEFAULT 0 "
            "COMMENT '最近一次总 IS bps',"
        ),
        "    last_fill_rate FLOAT NOT NULL DEFAULT 0 COMMENT '最近一次成交率',",
        (
            "    last_quality_score FLOAT NOT NULL DEFAULT 0 "
            "COMMENT '最近一次执行质量分',"
        ),
        (
            "    feedback_bias VARCHAR(16) NOT NULL DEFAULT 'NO_DATA' "
            "COMMENT 'NO_DATA/NEUTRAL/DEFENSIVE/AGGRESSIVE',"
        ),
        "    recommended_algo VARCHAR(32) NULL COMMENT '推荐算法类型',",
        (
            "    limit_offset_bps FLOAT NOT NULL DEFAULT 0 "
            "COMMENT 'LIMIT 偏移 bps',"
        ),
        (
            "    participation_rate_multiplier FLOAT NOT NULL DEFAULT 1 "
            "COMMENT '参与率乘数',"
        ),
        (
            "    pressure_high TINYINT(1) NOT NULL DEFAULT 0 "
            "COMMENT '是否高压力状态',"
        ),
        "    last_feedback_at DATETIME NULL COMMENT '最近一次反馈时间',",
        (
            "    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "COMMENT '创建时间',"
        ),
        (
            "    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',"
        ),
        "    PRIMARY KEY (id),",
        "    UNIQUE KEY ux_exec_policy_profile_key (",
        "        account_id,",
        "        symbol,",
        "        side,",
        "        urgency_bucket,",
        "        algo_type",
        "    ),",
        "    INDEX idx_exec_policy_profile_lookup (",
        "        account_id,",
        "        symbol,",
        "        side,",
        "        urgency_bucket",
        "    ),",
        "    INDEX idx_exec_policy_profile_last_feedback (last_feedback_at)",
        (
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 "
            "COMMENT='V10.5.3 执行策略长期反馈画像';"
        ),
    ]
)

MYSQL_DOWN = """
DROP TABLE IF EXISTS execution_policy_profiles;
"""


async def run_upgrade() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            print("[upgrade] Creating execution_policy_profiles table...")
            await conn.execute(text(MYSQL_UP))
            print(
                "[upgrade] ✓ execution_policy_profiles created "
                "(or already exists)"
            )
    finally:
        await engine.dispose()


async def run_rollback() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            print("[rollback] Dropping execution_policy_profiles table...")
            await conn.execute(text(MYSQL_DOWN))
            print("[rollback] ✓ execution_policy_profiles dropped")
    finally:
        await engine.dispose()


async def run_check() -> None:
    from sqlalchemy import text

    from app.models.db import engine

    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'execution_policy_profiles'"
                )
            )
            exists = bool(res.scalar())
            if not exists:
                print("[check] ✗ execution_policy_profiles does NOT exist")
                print("[check]   run upgrade_to_v10_5_3.py to create it")
                return

            rows = await conn.execute(
                text("SELECT COUNT(*) FROM execution_policy_profiles")
            )
            row_count = int(rows.scalar() or 0)
            print("[check] ✓ execution_policy_profiles exists")
            print(f"[check]   rows={row_count}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="V10.5.3 DB migration")
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

if __name__ == "__main__":
    main()
