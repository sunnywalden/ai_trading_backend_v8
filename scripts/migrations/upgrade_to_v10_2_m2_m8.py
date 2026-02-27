#!/usr/bin/env python3
"""V10.2 M2-M8: 数据库升级迁移脚本

新建表：
  - event_calendar_entries          (M2: 事件日历)
  - trade_attribution_entries       (M5: 交易归因)
  - ai_insight_repository           (M6: AI 经验库)
  - ab_experiments                  (M6: A/B 实验)

支持 MySQL 8.0 和 SQLite（开发/测试环境）。
支持 --rollback 回滚所有 M2-M8 表。

使用：
    python scripts/migrations/upgrade_to_v10_2_m2_m8.py
    python scripts/migrations/upgrade_to_v10_2_m2_m8.py --rollback
    python scripts/migrations/upgrade_to_v10_2_m2_m8.py --check
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# ── 路径配置 ─────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


async def get_db_engine():
    """根据 settings 创建合适的 AsyncEngine。"""
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = settings.DATABASE_URL
    kwargs: dict = {"echo": False}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}

    return create_async_engine(db_url, **kwargs)


# ── MySQL DDL ─────────────────────────────────────────────────────────────────

MYSQL_UP_STATEMENTS: list[str] = [
    # ── event_calendar_entries ───────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS event_calendar_entries (
        id                   INT AUTO_INCREMENT PRIMARY KEY,
        symbol               VARCHAR(32)  NOT NULL,
        event_type           VARCHAR(32)  NOT NULL,
        event_date           DATETIME     NOT NULL,
        title                VARCHAR(256) NOT NULL,
        description          TEXT,
        eps_estimate         DOUBLE,
        eps_actual           DOUBLE,
        revenue_estimate     DOUBLE,
        revenue_actual       DOUBLE,
        risk_level           VARCHAR(16)  NOT NULL DEFAULT 'MEDIUM',
        requires_fence       TINYINT(1)   NOT NULL DEFAULT 1,
        fence_applied        TINYINT(1)   NOT NULL DEFAULT 0,
        fence_applied_at     DATETIME,
        fence_overridden     TINYINT(1)   NOT NULL DEFAULT 0,
        fence_override_reason VARCHAR(512),
        source               VARCHAR(64)  NOT NULL DEFAULT 'yfinance',
        created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_event_symbol_date   (symbol, event_date),
        INDEX idx_event_type_date     (event_type, event_date),
        INDEX idx_event_fence_pending (fence_applied, event_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.2-M2 事件日历';
    """,

    # ── trade_attribution_entries ────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS trade_attribution_entries (
        id                      INT AUTO_INCREMENT PRIMARY KEY,
        position_id             INT,
        symbol                  VARCHAR(32)  NOT NULL,
        strategy_id             VARCHAR(128),
        entry_price             DOUBLE       NOT NULL DEFAULT 0,
        exit_price              DOUBLE       NOT NULL DEFAULT 0,
        quantity                DOUBLE       NOT NULL DEFAULT 0,
        pnl_absolute            DOUBLE       NOT NULL DEFAULT 0,
        pnl_pct                 DOUBLE       NOT NULL DEFAULT 0,
        hold_days               INT          NOT NULL DEFAULT 0,
        category                VARCHAR(16)  NOT NULL DEFAULT 'WIN',
        alpha_source            VARCHAR(64),
        alpha_contribution_pct  DOUBLE,
        alpha_detail            JSON,
        execution_score         DOUBLE,
        slippage_pct            DOUBLE,
        timing_score            DOUBLE,
        execution_detail        JSON,
        position_mgmt_score     DOUBLE,
        scale_in_count          INT          NOT NULL DEFAULT 0,
        scale_out_reason        VARCHAR(64),
        trailing_stop_used      TINYINT(1)   NOT NULL DEFAULT 0,
        position_detail         JSON,
        regime_at_entry         VARCHAR(32),
        regime_at_exit          VARCHAR(32),
        notes                   TEXT,
        created_at              DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_attr_symbol   (symbol),
        INDEX idx_attr_strategy (strategy_id),
        INDEX idx_attr_created  (created_at),
        INDEX idx_attr_category (category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.2-M5 交易归因';
    """,

    # ── ai_insight_repository ────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS ai_insight_repository (
        id               INT AUTO_INCREMENT PRIMARY KEY,
        insight_type     VARCHAR(32)  NOT NULL,
        regime           VARCHAR(32),
        symbol           VARCHAR(32),
        strategy_id      VARCHAR(128),
        title            VARCHAR(256) NOT NULL,
        summary          TEXT         NOT NULL,
        evidence         JSON,
        actionable_rule  JSON,
        confidence       DOUBLE       NOT NULL DEFAULT 0.5,
        win_rate_impact  DOUBLE,
        validated        TINYINT(1)   NOT NULL DEFAULT 0,
        active           TINYINT(1)   NOT NULL DEFAULT 1,
        applied_count    INT          NOT NULL DEFAULT 0,
        success_count    INT          NOT NULL DEFAULT 0,
        created_by_job   VARCHAR(64)  NOT NULL DEFAULT 'weekly_insight_job',
        created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_insight_type       (insight_type),
        INDEX idx_insight_regime     (regime),
        INDEX idx_insight_active     (active),
        INDEX idx_insight_confidence (confidence)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.2-M6 AI 经验库';
    """,

    # ── ab_experiments ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS ab_experiments (
        id                   INT AUTO_INCREMENT PRIMARY KEY,
        insight_id           INT,
        experiment_name      VARCHAR(256) NOT NULL,
        param_key            VARCHAR(128) NOT NULL,
        control_value        JSON,
        treatment_value      JSON,
        status               VARCHAR(16)  NOT NULL DEFAULT 'RUNNING',
        start_date           DATETIME     NOT NULL,
        end_date             DATETIME,
        duration_days        INT          NOT NULL DEFAULT 14,
        control_win_rate     DOUBLE,
        treatment_win_rate   DOUBLE,
        control_trades       INT,
        treatment_trades     INT,
        p_value              DOUBLE,
        passed_significance  TINYINT(1)   NOT NULL DEFAULT 0,
        auto_applied         TINYINT(1)   NOT NULL DEFAULT 0,
        notes                TEXT,
        created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_ab_status  (status),
        INDEX idx_ab_start   (start_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.2-M6 A/B 实验';
    """,
]

MYSQL_DOWN_STATEMENTS: list[str] = [
    "DROP TABLE IF EXISTS ab_experiments;",
    "DROP TABLE IF EXISTS ai_insight_repository;",
    "DROP TABLE IF EXISTS trade_attribution_entries;",
    "DROP TABLE IF EXISTS event_calendar_entries;",
]

# ── SQLite DDL（dev/test 环境）────────────────────────────────────────────────

SQLITE_UP_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS event_calendar_entries (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol                TEXT    NOT NULL,
        event_type            TEXT    NOT NULL,
        event_date            TEXT    NOT NULL,
        title                 TEXT    NOT NULL,
        description           TEXT,
        eps_estimate          REAL,
        eps_actual            REAL,
        revenue_estimate      REAL,
        revenue_actual        REAL,
        risk_level            TEXT    NOT NULL DEFAULT 'MEDIUM',
        requires_fence        INTEGER NOT NULL DEFAULT 1,
        fence_applied         INTEGER NOT NULL DEFAULT 0,
        fence_applied_at      TEXT,
        fence_overridden      INTEGER NOT NULL DEFAULT 0,
        fence_override_reason TEXT,
        source                TEXT    NOT NULL DEFAULT 'yfinance',
        created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at            TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_event_symbol_date ON event_calendar_entries(symbol, event_date)",
    "CREATE INDEX IF NOT EXISTS idx_event_type_date ON event_calendar_entries(event_type, event_date)",

    """
    CREATE TABLE IF NOT EXISTS trade_attribution_entries (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id            INTEGER,
        symbol                 TEXT    NOT NULL,
        strategy_id            TEXT,
        entry_price            REAL    NOT NULL DEFAULT 0,
        exit_price             REAL    NOT NULL DEFAULT 0,
        quantity               REAL    NOT NULL DEFAULT 0,
        pnl_absolute           REAL    NOT NULL DEFAULT 0,
        pnl_pct                REAL    NOT NULL DEFAULT 0,
        hold_days              INTEGER NOT NULL DEFAULT 0,
        category               TEXT    NOT NULL DEFAULT 'WIN',
        alpha_source           TEXT,
        alpha_contribution_pct REAL,
        alpha_detail           TEXT,
        execution_score        REAL,
        slippage_pct           REAL,
        timing_score           REAL,
        execution_detail       TEXT,
        position_mgmt_score    REAL,
        scale_in_count         INTEGER NOT NULL DEFAULT 0,
        scale_out_reason       TEXT,
        trailing_stop_used     INTEGER NOT NULL DEFAULT 0,
        position_detail        TEXT,
        regime_at_entry        TEXT,
        regime_at_exit         TEXT,
        notes                  TEXT,
        created_at             TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS ai_insight_repository (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        insight_type    TEXT    NOT NULL,
        regime          TEXT,
        symbol          TEXT,
        strategy_id     TEXT,
        title           TEXT    NOT NULL,
        summary         TEXT    NOT NULL,
        evidence        TEXT,
        actionable_rule TEXT,
        confidence      REAL    NOT NULL DEFAULT 0.5,
        win_rate_impact REAL,
        validated       INTEGER NOT NULL DEFAULT 0,
        active          INTEGER NOT NULL DEFAULT 1,
        applied_count   INTEGER NOT NULL DEFAULT 0,
        success_count   INTEGER NOT NULL DEFAULT 0,
        created_by_job  TEXT    NOT NULL DEFAULT 'weekly_insight_job',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS ab_experiments (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        insight_id           INTEGER,
        experiment_name      TEXT    NOT NULL,
        param_key            TEXT    NOT NULL,
        control_value        TEXT,
        treatment_value      TEXT,
        status               TEXT    NOT NULL DEFAULT 'RUNNING',
        start_date           TEXT    NOT NULL,
        end_date             TEXT,
        duration_days        INTEGER NOT NULL DEFAULT 14,
        control_win_rate     REAL,
        treatment_win_rate   REAL,
        control_trades       INTEGER,
        treatment_trades     INTEGER,
        p_value              REAL,
        passed_significance  INTEGER NOT NULL DEFAULT 0,
        auto_applied         INTEGER NOT NULL DEFAULT 0,
        notes                TEXT,
        created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
]

SQLITE_DOWN_STATEMENTS: list[str] = [
    "DROP TABLE IF EXISTS ab_experiments",
    "DROP TABLE IF EXISTS ai_insight_repository",
    "DROP TABLE IF EXISTS trade_attribution_entries",
    "DROP TABLE IF EXISTS event_calendar_entries",
]


# ── 执行函数 ──────────────────────────────────────────────────────────────────

async def run_migration(rollback: bool = False, check: bool = False) -> None:
    engine = await get_db_engine()
    url    = str(engine.url)
    is_sqlite = "sqlite" in url

    if is_sqlite:
        up_stmts   = SQLITE_UP_STATEMENTS
        down_stmts = SQLITE_DOWN_STATEMENTS
        dialect    = "sqlite"
    else:
        up_stmts   = MYSQL_UP_STATEMENTS
        down_stmts = MYSQL_DOWN_STATEMENTS
        dialect    = "mysql"

    stmts = down_stmts if rollback else up_stmts
    action = "ROLLBACK" if rollback else "UPGRADE"

    if check:
        print(f"[CHECK] dialect={dialect}, statements to run: {len(up_stmts)}")
        print("Tables to CREATE: event_calendar_entries, trade_attribution_entries, ai_insight_repository, ab_experiments")
        await engine.dispose()
        return

    print(f"[V10.2 M2-M8 {action}] dialect={dialect}, running {len(stmts)} statements...")

    from sqlalchemy import text

    async with engine.begin() as conn:
        for i, sql in enumerate(stmts, 1):
            sql = sql.strip()
            if not sql:
                continue
            try:
                await conn.execute(text(sql))
                print(f"  [{i}/{len(stmts)}] ✓  {sql[:60].replace(chr(10), ' ')}...")
            except Exception as e:
                print(f"  [{i}/{len(stmts)}] ✗  {sql[:60]}... ERROR: {e}")
                raise

    await engine.dispose()
    print(f"[V10.2 M2-M8 {action}] ✅ Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V10.2 M2-M8 DB migration")
    parser.add_argument("--rollback", action="store_true", help="回滚所有 M2-M8 新表")
    parser.add_argument("--check",    action="store_true", help="仅检查，不执行 DDL")
    args = parser.parse_args()

    asyncio.run(run_migration(rollback=args.rollback, check=args.check))
