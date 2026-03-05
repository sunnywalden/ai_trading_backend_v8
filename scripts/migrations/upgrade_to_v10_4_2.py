#!/usr/bin/env python3
"""upgrade_to_v10_4_2.py — V10.4.2 数据库迁移脚本

差异对比（v10.4.1 → v10.4.2）：

  v10.4.2（本脚本）—— 信号精英化：高置信度多维共振门控
  ─────────────────────────────────────────────────────
  1. signal_quality_audit_logs  信号漏斗审计日志
  2. ghost_trades               幽灵交易（被拒信号的虚拟跟踪）

用法：
  cd /path/to/ai_trading_backend_v8
  python scripts/migrations/upgrade_to_v10_4_2.py
  python scripts/migrations/upgrade_to_v10_4_2.py --check
  python scripts/migrations/upgrade_to_v10_4_2.py --rollback
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP_AUDIT = """
CREATE TABLE IF NOT EXISTS signal_quality_audit_logs (
    id                      BIGINT          NOT NULL AUTO_INCREMENT      COMMENT '主键',
    signal_id               BIGINT          NULL                         COMMENT '关联信号 ID',
    symbol                  VARCHAR(32)     NOT NULL                     COMMENT '标的代码',
    funnel_result           VARCHAR(16)     NOT NULL                     COMMENT 'PASSED / REJECTED',
    rejected_at_layer       TINYINT         NULL                         COMMENT '0-4',
    rejection_reason        VARCHAR(64)     NULL                         COMMENT '拒绝原因枚举',
    rejection_detail        TEXT            NULL                         COMMENT '拒绝详情',
    conviction_score        FLOAT           NULL                         COMMENT '置信度得分 (0-100)',
    composite_score         FLOAT           NULL                         COMMENT '融合置信度 (0-100)',
    resonance_bonus         FLOAT           NULL                         COMMENT '共振奖励分',
    regime_alignment        FLOAT           NULL                         COMMENT '体制对齐分',
    aligned_count           TINYINT         NULL                         COMMENT '同向维度数',
    aligned_dims            JSON            NULL                         COMMENT '同向维度名列表',
    opposing_dims           JSON            NULL                         COMMENT '反向维度名列表',
    neutral_dims            JSON            NULL                         COMMENT '中性维度名列表',
    anti_resonance_triggered TINYINT(1)     NOT NULL DEFAULT 0           COMMENT '是否触发反共振熔断',
    signal_direction        VARCHAR(16)     NULL                         COMMENT 'LONG / SHORT / HOLD',
    regime                  VARCHAR(32)     NULL                         COMMENT '评估时的市场体制',
    concurrent_positions    SMALLINT        NULL                         COMMENT '评估时的并发仓位数',
    daily_signals_used      SMALLINT        NULL                         COMMENT '当日已使用信号配额',
    generated_at            DATETIME        NULL                         COMMENT '信号原始生成时间',
    created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    PRIMARY KEY (id),
    INDEX idx_sqal_symbol_created  (symbol, created_at),
    INDEX idx_sqal_funnel_result   (funnel_result, created_at),
    INDEX idx_sqal_signal_id       (signal_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.4.2 信号品质漏斗审计日志';
"""

MYSQL_UP_GHOST = """
CREATE TABLE IF NOT EXISTS ghost_trades (
    id                          BIGINT      NOT NULL AUTO_INCREMENT      COMMENT '主键',
    signal_id                   BIGINT      NULL                         COMMENT '关联信号ID',
    audit_log_id                BIGINT      NULL                         COMMENT '关联审计日志ID',
    symbol                      VARCHAR(32) NOT NULL                     COMMENT '标的代码',
    direction                   VARCHAR(16) NOT NULL                     COMMENT 'LONG / SHORT',
    rejection_reason            VARCHAR(64) NULL                         COMMENT '被拒原因',
    rejected_at_layer           TINYINT     NULL                         COMMENT '被拒层级(0-4)',
    conviction_score_at_rejection FLOAT     NULL                         COMMENT '被拒时置信度',
    entry_price                 FLOAT       NULL                         COMMENT '进入价',
    stop_loss                   FLOAT       NULL                         COMMENT '止损价',
    take_profit                 FLOAT       NULL                         COMMENT '止盈价',
    last_price                  FLOAT       NULL                         COMMENT '最新价格',
    highest_price               FLOAT       NULL                         COMMENT '跟踪期最高价',
    lowest_price                FLOAT       NULL                         COMMENT '跟踪期最低价',
    ghost_pnl_pct               FLOAT       NULL                         COMMENT '幽灵PnL百分比',
    ghost_pnl_abs               FLOAT       NULL                         COMMENT '幽灵PnL绝对值(名义100单位)',
    ghost_result                VARCHAR(16) NOT NULL DEFAULT 'OPEN'      COMMENT 'WIN/LOSS/OPEN/EXPIRED',
    tracking_day                SMALLINT    NOT NULL DEFAULT 0           COMMENT '已跟踪天数',
    max_tracking_days           SMALLINT    NOT NULL DEFAULT 10          COMMENT '最大跟踪天数',
    price_history               JSON        NULL                         COMMENT '价格历史数组',
    tracking_start              DATETIME    NULL                         COMMENT '开始跟踪时间',
    tracking_end                DATETIME    NULL                         COMMENT '结束跟踪时间',
    created_at                  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    PRIMARY KEY (id),
    INDEX idx_gt_symbol_result   (symbol, ghost_result),
    INDEX idx_gt_tracking_start  (tracking_start),
    INDEX idx_gt_signal_id       (signal_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.4.2 幽灵交易（被拒信号虚拟跟踪）';
"""

# ─────────────────────────────────────────────────────────────────────────────
# SQLite DDL（本地开发环境）
# ─────────────────────────────────────────────────────────────────────────────

SQLITE_UP_AUDIT = """
CREATE TABLE IF NOT EXISTS signal_quality_audit_logs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id                INTEGER,
    symbol                   TEXT    NOT NULL,
    funnel_result            TEXT    NOT NULL,
    rejected_at_layer        INTEGER,
    rejection_reason         TEXT,
    rejection_detail         TEXT,
    conviction_score         REAL,
    composite_score          REAL,
    resonance_bonus          REAL,
    regime_alignment         REAL,
    aligned_count            INTEGER,
    aligned_dims             TEXT,
    opposing_dims            TEXT,
    neutral_dims             TEXT,
    anti_resonance_triggered INTEGER NOT NULL DEFAULT 0,
    signal_direction         TEXT,
    regime                   TEXT,
    concurrent_positions     INTEGER,
    daily_signals_used       INTEGER,
    generated_at             TEXT,
    created_at               TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

SQLITE_UP_GHOST = """
CREATE TABLE IF NOT EXISTS ghost_trades (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id                     INTEGER,
    audit_log_id                  INTEGER,
    symbol                        TEXT    NOT NULL,
    direction                     TEXT    NOT NULL,
    rejection_reason              TEXT,
    rejected_at_layer             INTEGER,
    conviction_score_at_rejection REAL,
    entry_price                   REAL,
    stop_loss                     REAL,
    take_profit                   REAL,
    last_price                    REAL,
    highest_price                 REAL,
    lowest_price                  REAL,
    ghost_pnl_pct                 REAL,
    ghost_pnl_abs                 REAL,
    ghost_result                  TEXT    NOT NULL DEFAULT 'OPEN',
    tracking_day                  INTEGER NOT NULL DEFAULT 0,
    max_tracking_days             INTEGER NOT NULL DEFAULT 10,
    price_history                 TEXT,
    tracking_start                TEXT,
    tracking_end                  TEXT,
    created_at                    TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

SQLITE_INDEXES_AUDIT = [
    "CREATE INDEX IF NOT EXISTS idx_sqal_symbol_created ON signal_quality_audit_logs(symbol, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_sqal_funnel_result  ON signal_quality_audit_logs(funnel_result, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_sqal_signal_id      ON signal_quality_audit_logs(signal_id);",
]

SQLITE_INDEXES_GHOST = [
    "CREATE INDEX IF NOT EXISTS idx_gt_symbol_result  ON ghost_trades(symbol, ghost_result);",
    "CREATE INDEX IF NOT EXISTS idx_gt_tracking_start ON ghost_trades(tracking_start);",
    "CREATE INDEX IF NOT EXISTS idx_gt_signal_id      ON ghost_trades(signal_id);",
]

ROLLBACK_DOWN = """
DROP TABLE IF EXISTS ghost_trades;
DROP TABLE IF EXISTS signal_quality_audit_logs;
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_engine():
    from app.models.db import engine
    return engine


async def _is_mysql(engine) -> bool:
    return "mysql" in str(engine.url).lower()


async def _table_exists(conn, table: str, is_mysql: bool) -> bool:
    from sqlalchemy import text
    if is_mysql:
        row = await conn.execute(
            text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=:t"),
            {"t": table},
        )
    else:
        row = await conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        )
    return (await row.scalar() if hasattr(row, "scalar") else row.scalar_one()) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Check
# ─────────────────────────────────────────────────────────────────────────────

async def check() -> None:
    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    print(f"[Check] Database: {'MySQL' if is_mysql else 'SQLite'}")
    async with engine.connect() as conn:
        for tbl in ("signal_quality_audit_logs", "ghost_trades"):
            exists = await _table_exists(conn, tbl, is_mysql)
            status = "✅ EXISTS" if exists else "❌ MISSING"
            print(f"  {status}  {tbl}")


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────────────

async def upgrade() -> None:
    from sqlalchemy import text
    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    print(f"[Upgrade] Database: {'MySQL' if is_mysql else 'SQLite'}")

    async with engine.begin() as conn:
        if is_mysql:
            await conn.execute(text(MYSQL_UP_AUDIT))
            print("  ✅ signal_quality_audit_logs — created (or already exists)")
            await conn.execute(text(MYSQL_UP_GHOST))
            print("  ✅ ghost_trades — created (or already exists)")
        else:
            await conn.execute(text(SQLITE_UP_AUDIT))
            for idx in SQLITE_INDEXES_AUDIT:
                await conn.execute(text(idx))
            print("  ✅ signal_quality_audit_logs — created (or already exists)")
            await conn.execute(text(SQLITE_UP_GHOST))
            for idx in SQLITE_INDEXES_GHOST:
                await conn.execute(text(idx))
            print("  ✅ ghost_trades — created (or already exists)")

    print("[Upgrade] V10.4.2 migration completed ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Rollback
# ─────────────────────────────────────────────────────────────────────────────

async def rollback() -> None:
    from sqlalchemy import text
    engine = await _get_engine()
    async with engine.begin() as conn:
        for stmt in ROLLBACK_DOWN.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt + ";"))
    print("[Rollback] Tables ghost_trades + signal_quality_audit_logs dropped ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V10.4.2 DB Migration")
    parser.add_argument("--check",    action="store_true", help="检查表是否存在")
    parser.add_argument("--rollback", action="store_true", help="回滚（删除新增表）")
    args = parser.parse_args()

    if args.check:
        asyncio.run(check())
    elif args.rollback:
        asyncio.run(rollback())
    else:
        asyncio.run(upgrade())
