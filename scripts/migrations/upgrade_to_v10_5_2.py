#!/usr/bin/env python3
"""upgrade_to_v10_5_2.py — V10.5.2 数据库迁移脚本

差异对比（v10.5.1 → v10.5.2）：

  v10.5.2（本脚本）—— 席位竞争准入与资本配置闭环
  ──────────────────────────────────────────────────────
  1. capacity_decision_logs  席位竞争仲裁审计日志（CapacityArbiterService 写入）

用法：
  cd /path/to/ai_trading_backend_v8
  python scripts/migrations/upgrade_to_v10_5_2.py
  python scripts/migrations/upgrade_to_v10_5_2.py --check
  python scripts/migrations/upgrade_to_v10_5_2.py --rollback
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP = """
CREATE TABLE IF NOT EXISTS capacity_decision_logs (
    id                      BIGINT          NOT NULL AUTO_INCREMENT      COMMENT '主键',
    account_id              VARCHAR(64)     NOT NULL                     COMMENT '账户 ID',
    cycle_id                VARCHAR(64)     NULL                         COMMENT '决策周期唯一 ID',
    regime                  VARCHAR(32)     NULL                         COMMENT '仲裁时的市场体制',
    trigger_reason          VARCHAR(64)     NOT NULL DEFAULT 'CAPACITY_OVERFLOW' COMMENT '触发原因',
    max_positions           SMALLINT        NOT NULL                     COMMENT '持仓上限',
    positions_count         SMALLINT        NOT NULL                     COMMENT '仲裁时当前持仓数',
    signals_count           SMALLINT        NOT NULL                     COMMENT '参与竞争的信号数',
    overflow_count          SMALLINT        NOT NULL                     COMMENT 'N=持仓+信号-上限',
    candidates_snapshot     JSON            NULL                         COMMENT '候选池快照数组',
    eliminated_positions    JSON            NULL                         COMMENT '被淘汰持仓列表',
    eliminated_signals      JSON            NULL                         COMMENT '被淘汰信号列表',
    approved_signals        JSON            NULL                         COMMENT '审批通过信号列表',
    min_edge_protected      SMALLINT        NOT NULL DEFAULT 0           COMMENT '因 MIN_REPLACEMENT_EDGE 保护数',
    cooldown_protected      SMALLINT        NOT NULL DEFAULT 0           COMMENT '因冷却期保护数',
    min_hold_protected      SMALLINT        NOT NULL DEFAULT 0           COMMENT '因最小持有时间保护数',
    max_replacements_cap    SMALLINT        NOT NULL DEFAULT 0           COMMENT '因每周期上限中止数',
    dry_run                 TINYINT(1)      NOT NULL DEFAULT 0           COMMENT '是否仅评估不执行',
    replacement_triggered   TINYINT(1)      NOT NULL DEFAULT 0           COMMENT '是否触发了实际平仓',
    created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    PRIMARY KEY (id),
    INDEX ix_cdl_account_created   (account_id, created_at),
    INDEX ix_cdl_cycle_id          (cycle_id),
    INDEX ix_cdl_replacement       (replacement_triggered, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.5.2 席位竞争仲裁审计日志';
"""

MYSQL_DOWN = """
DROP TABLE IF EXISTS capacity_decision_logs;
"""

# ─────────────────────────────────────────────────────────────────────────────
# 执行逻辑
# ─────────────────────────────────────────────────────────────────────────────


async def run_upgrade() -> None:
    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            print("[upgrade] Creating capacity_decision_logs table...")
            await conn.execute(__import__("sqlalchemy").text(MYSQL_UP))
            print("[upgrade] ✓ capacity_decision_logs created (or already exists)")
    finally:
        await engine.dispose()


async def run_rollback() -> None:
    from app.models.db import engine

    try:
        async with engine.begin() as conn:
            print("[rollback] Dropping capacity_decision_logs table...")
            await conn.execute(__import__("sqlalchemy").text(MYSQL_DOWN))
            print("[rollback] ✓ capacity_decision_logs dropped")
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
                    "WHERE table_schema = DATABASE() AND table_name = 'capacity_decision_logs'"
                )
            )
            count = res.scalar()
            if count:
                res2 = await conn.execute(
                    text("SELECT COUNT(*) FROM capacity_decision_logs")
                )
                rows = res2.scalar()
                print(f"[check] ✓ capacity_decision_logs exists — {rows} rows")
            else:
                print(
                    "[check] ✗ capacity_decision_logs does NOT exist — run without --check to create"
                )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="V10.5.2 DB migration")
    parser.add_argument("--rollback", action="store_true", help="Roll back migration")
    parser.add_argument(
        "--check", action="store_true", help="Check migration status only"
    )
    args = parser.parse_args()

    if args.rollback:
        asyncio.run(run_rollback())
    elif args.check:
        asyncio.run(run_check())
    else:
        asyncio.run(run_upgrade())


if __name__ == "__main__":
    main()
