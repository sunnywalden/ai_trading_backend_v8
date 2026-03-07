#!/usr/bin/env python3
"""upgrade_to_v10_4_4.py — V10.4.4 数据库迁移脚本

差异对比（v10.4.2 → v10.4.4）：

  v10.4.4（本脚本）—— Position-centric 生命周期
  ─────────────────────────────────────────────────────
  新增表：
  1. positions                    仓位聚合根
  2. execution_slices             执行切片（Position 的动作单元）
  3. position_lifecycle_events    仓位生命周期事件时间线（Append-Only 审计）

  修改表：
  4. autonomous_execution_intent  新增 position_id / execution_slice_id 两列

用法：
  cd /path/to/ai_trading_backend_v8
  python scripts/migrations/upgrade_to_v10_4_4.py           # 执行迁移
  python scripts/migrations/upgrade_to_v10_4_4.py --check   # 检查现状
  python scripts/migrations/upgrade_to_v10_4_4.py --rollback # 回滚（危险！）
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
# MySQL DDL — 新增表
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_UP_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    id                      BIGINT          NOT NULL AUTO_INCREMENT          COMMENT '主键',
    account_id              VARCHAR(64)     NOT NULL                         COMMENT '账户ID',
    symbol                  VARCHAR(32)     NOT NULL                         COMMENT '标的代码',
    thesis_key              VARCHAR(64)     NOT NULL DEFAULT 'default'       COMMENT '主题键（区分同账户同标的多主题仓位）',
    status                  VARCHAR(32)     NOT NULL DEFAULT 'PENDING'       COMMENT 'PositionStatus 枚举值',
    direction               VARCHAR(8)      NOT NULL DEFAULT 'LONG'          COMMENT 'LONG / SHORT',
    total_qty               FLOAT           NOT NULL DEFAULT 0.0             COMMENT '当前持有总数量',
    filled_qty              FLOAT           NOT NULL DEFAULT 0.0             COMMENT '累计成交数量',
    open_qty                FLOAT           NOT NULL DEFAULT 0.0             COMMENT '已开仓数量',
    closed_qty              FLOAT           NOT NULL DEFAULT 0.0             COMMENT '累计已平仓数量',
    avg_entry_price         FLOAT           NULL                             COMMENT '平均入场价',
    avg_close_price         FLOAT           NULL                             COMMENT '平均平仓价',
    realized_pnl            FLOAT           NOT NULL DEFAULT 0.0             COMMENT '已实现盈亏',
    unrealized_pnl          FLOAT           NULL                             COMMENT '未实现盈亏',
    unrealized_pnl_pct      FLOAT           NULL                             COMMENT '未实现盈亏百分比',
    stop_loss_price         FLOAT           NULL                             COMMENT '止损价',
    take_profit_price       FLOAT           NULL                             COMMENT '止盈价',
    trailing_high           FLOAT           NULL                             COMMENT '追踪止损历史最高价',
    max_holding_days        INT             NULL                             COMMENT '最大持仓天数',
    initial_signal_id       BIGINT          NULL                             COMMENT '触发开仓的 TradingSignal.id',
    initial_signal_uid      VARCHAR(64)     NULL                             COMMENT '触发开仓的 TradingSignal.signal_id（UUID）',
    latest_plan_id          BIGINT          NULL                             COMMENT '最近关联的 TradingPlan.id',
    closing_reason          VARCHAR(32)     NULL                             COMMENT 'ClosingReason 枚举值',
    closing_source          VARCHAR(32)     NULL                             COMMENT 'ExecutionPath 枚举值',
    closing_note            TEXT            NULL                             COMMENT '人工备注 / AI 关闭摘要',
    exemption_active        TINYINT(1)      NOT NULL DEFAULT 0               COMMENT '是否有活跃豁免',
    exemption_reason        TEXT            NULL                             COMMENT '豁免原因',
    governance_flag         VARCHAR(32)     NULL                             COMMENT 'NORMAL / WATCHLIST / ESCALATED / SUSPENDED',
    opened_at               DATETIME        NULL                             COMMENT '第一笔成交时间',
    closed_at               DATETIME        NULL                             COMMENT '平仓完成时间',
    last_action_at          DATETIME        NULL                             COMMENT '最后一次 ExecutionSlice 动作时间',
    created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    updated_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uq_position_account_symbol_thesis (account_id, symbol, thesis_key),
    INDEX idx_position_account_id    (account_id),
    INDEX idx_position_symbol        (symbol),
    INDEX idx_position_status        (status),
    INDEX idx_position_account_status (account_id, status),
    INDEX idx_position_symbol_status  (symbol, status),
    INDEX idx_position_closed_at      (closed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.4.4 仓位聚合根';
"""

MYSQL_UP_EXECUTION_SLICES = """
CREATE TABLE IF NOT EXISTS execution_slices (
    id                  BIGINT          NOT NULL AUTO_INCREMENT      COMMENT '主键',
    position_id         BIGINT          NOT NULL                     COMMENT '关联 positions.id',
    account_id          VARCHAR(64)     NOT NULL                     COMMENT '账户ID',
    symbol              VARCHAR(32)     NOT NULL                     COMMENT '标的代码',
    action              VARCHAR(16)     NOT NULL                     COMMENT 'SliceAction 枚举值',
    status              VARCHAR(32)     NOT NULL DEFAULT 'PENDING'   COMMENT 'SliceStatus 枚举值',
    requested_qty       FLOAT           NOT NULL DEFAULT 0.0         COMMENT '目标数量',
    submitted_qty       FLOAT           NOT NULL DEFAULT 0.0         COMMENT '已提交数量',
    filled_qty          FLOAT           NOT NULL DEFAULT 0.0         COMMENT '已成交数量',
    avg_fill_price      FLOAT           NULL                         COMMENT '平均成交价',
    signal_id           VARCHAR(64)     NULL                         COMMENT '触发本切片的 TradingSignal.signal_id（UUID）',
    signal_db_id        BIGINT          NULL                         COMMENT '关联 TradingSignal.id',
    intent_id           VARCHAR(64)     NULL                         COMMENT '关联 AutonomousExecutionIntent.intent_id（兼容旧链路）',
    execution_path      VARCHAR(32)     NULL                         COMMENT 'ExecutionPath 枚举值',
    autonomy_level      VARCHAR(16)     NULL                         COMMENT 'FULL / SEMI / ADVISORY',
    closing_reason      VARCHAR(32)     NULL                         COMMENT 'ClosingReason 枚举值（REDUCE/CLOSE 切片）',
    exemption_applied   TINYINT(1)      NOT NULL DEFAULT 0           COMMENT '是否应用了豁免',
    exemption_detail    TEXT            NULL                         COMMENT '豁免详情',
    order_ids           JSON            NULL                         COMMENT 'broker 订单ID列表',
    broker_ref          VARCHAR(128)    NULL                         COMMENT '主要 broker 订单ID',
    error_message       TEXT            NULL                         COMMENT '错误消息',
    retry_count         INT             NOT NULL DEFAULT 0           COMMENT '重试次数',
    submitted_at        DATETIME        NULL                         COMMENT '提交时间',
    filled_at           DATETIME        NULL                         COMMENT '成交完成时间',
    stuck_at            DATETIME        NULL                         COMMENT '进入 STUCK 状态的时间',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
    PRIMARY KEY (id),
    INDEX idx_slice_position_id      (position_id),
    INDEX idx_slice_account_id       (account_id),
    INDEX idx_slice_status           (status),
    INDEX idx_slice_account_status   (account_id, status),
    INDEX idx_slice_stuck_at         (stuck_at),
    CONSTRAINT fk_slice_position FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.4.4 执行切片（Position 的动作单元）';
"""

MYSQL_UP_POSITION_LIFECYCLE_EVENTS = """
CREATE TABLE IF NOT EXISTS position_lifecycle_events (
    id              BIGINT          NOT NULL AUTO_INCREMENT      COMMENT '主键',
    position_id     BIGINT          NOT NULL                     COMMENT '关联 positions.id',
    slice_id        BIGINT          NULL                         COMMENT '关联 execution_slices.id（可空）',
    kind            VARCHAR(32)     NOT NULL                     COMMENT 'EventKind 枚举值',
    summary         VARCHAR(256)    NOT NULL                     COMMENT '人类可读摘要（前端 timeline 展示）',
    detail          TEXT            NULL                         COMMENT '详细描述 / AI 推理 / 错误消息',
    from_status     VARCHAR(32)     NULL                         COMMENT 'STATE_TRANSITION：迁移前状态',
    to_status       VARCHAR(32)     NULL                         COMMENT 'STATE_TRANSITION：迁移后状态',
    actor           VARCHAR(64)     NULL                         COMMENT '事件触发者',
    signal_id       VARCHAR(64)     NULL                         COMMENT '关联信号ID',
    intent_id       VARCHAR(64)     NULL                         COMMENT '关联 intent_id',
    metadata_json   JSON            NULL                         COMMENT '附加上下文快照',
    occurred_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '事件发生时间（UTC）',
    PRIMARY KEY (id),
    INDEX idx_ple_position_id        (position_id),
    INDEX idx_ple_slice_id           (slice_id),
    INDEX idx_ple_kind               (kind),
    INDEX idx_ple_occurred_at        (occurred_at),
    INDEX idx_ple_position_occurred  (position_id, occurred_at),
    INDEX idx_ple_kind_occurred      (kind, occurred_at),
    CONSTRAINT fk_ple_position FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE,
    CONSTRAINT fk_ple_slice    FOREIGN KEY (slice_id)    REFERENCES execution_slices(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.4.4 仓位生命周期事件时间线（Append-Only 审计）';
"""

# ─────────────────────────────────────────────────────────────────────────────
# MySQL DDL — ALTER 现有表（autonomous_execution_intent）
# ─────────────────────────────────────────────────────────────────────────────

MYSQL_ALTER_INTENT_POSITION_ID = """
ALTER TABLE autonomous_execution_intent
    ADD COLUMN position_id BIGINT NULL COMMENT '关联的 positions.id（V10.4.4 新增，旧记录为 NULL）',
    ADD INDEX  idx_exec_intent_position_id (position_id);
"""

MYSQL_ALTER_INTENT_SLICE_ID = """
ALTER TABLE autonomous_execution_intent
    ADD COLUMN execution_slice_id BIGINT NULL COMMENT '关联的 execution_slices.id（V10.4.4 新增，旧记录为 NULL）',
    ADD INDEX  idx_exec_intent_slice_id (execution_slice_id);
"""

# ─────────────────────────────────────────────────────────────────────────────
# Rollback DDL
# ─────────────────────────────────────────────────────────────────────────────

ROLLBACK_DROP_TABLES = [
    "DROP TABLE IF EXISTS position_lifecycle_events;",
    "DROP TABLE IF EXISTS execution_slices;",
    "DROP TABLE IF EXISTS positions;",
]

ROLLBACK_ALTER_INTENT = [
    "ALTER TABLE autonomous_execution_intent DROP INDEX  idx_exec_intent_position_id;",
    "ALTER TABLE autonomous_execution_intent DROP COLUMN position_id;",
    "ALTER TABLE autonomous_execution_intent DROP INDEX  idx_exec_intent_slice_id;",
    "ALTER TABLE autonomous_execution_intent DROP COLUMN execution_slice_id;",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _get_engine():
    from app.models.db import engine

    return engine


async def _is_mysql(engine) -> bool:
    return "mysql" in str(engine.url).lower()


async def _table_exists(conn, table: str) -> bool:
    from sqlalchemy import text

    row = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=:t"
        ),
        {"t": table},
    )
    return row.scalar_one() > 0


async def _column_exists(conn, table: str, column: str) -> bool:
    from sqlalchemy import text

    row = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    )
    return row.scalar_one() > 0


async def _index_exists(conn, table: str, index: str) -> bool:
    from sqlalchemy import text

    row = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema=DATABASE() AND table_name=:t AND index_name=:i"
        ),
        {"t": table, "i": index},
    )
    return row.scalar_one() > 0


# ─────────────────────────────────────────────────────────────────────────────
# Check
# ─────────────────────────────────────────────────────────────────────────────


async def check() -> None:
    from sqlalchemy import text

    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    if not is_mysql:
        print(
            "[Check] WARNING — non-MySQL database detected; this script targets MySQL only."
        )
        return
    print("[Check] Database: MySQL")
    async with engine.connect() as conn:
        for tbl in ("positions", "execution_slices", "position_lifecycle_events"):
            exists = await _table_exists(conn, tbl)
            print(f"  {'✅ EXISTS' if exists else '❌ MISSING'}  table: {tbl}")

        for col in ("position_id", "execution_slice_id"):
            exists = await _column_exists(conn, "autonomous_execution_intent", col)
            print(
                f"  {'✅ EXISTS' if exists else '❌ MISSING'}  autonomous_execution_intent.{col}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────────────


async def upgrade() -> None:
    from sqlalchemy import text

    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    if not is_mysql:
        print("[Upgrade] ERROR — non-MySQL database. This script only supports MySQL.")
        sys.exit(1)

    print("[Upgrade] Database: MySQL")

    async with engine.begin() as conn:
        # ── 新建表（顺序重要：positions 先于依赖它的表）────────────────────────
        await conn.execute(text(MYSQL_UP_POSITIONS))
        print("  ✅ positions — created (or already exists)")

        await conn.execute(text(MYSQL_UP_EXECUTION_SLICES))
        print("  ✅ execution_slices — created (or already exists)")

        await conn.execute(text(MYSQL_UP_POSITION_LIFECYCLE_EVENTS))
        print("  ✅ position_lifecycle_events — created (or already exists)")

        # ── ALTER autonomous_execution_intent：position_id ─────────────────────
        col_pos_exists = await _column_exists(
            conn, "autonomous_execution_intent", "position_id"
        )
        if col_pos_exists:
            print(
                "  ⏭  autonomous_execution_intent.position_id — already exists, skipped"
            )
        else:
            await conn.execute(text(MYSQL_ALTER_INTENT_POSITION_ID))
            print("  ✅ autonomous_execution_intent.position_id — added")

        # ── ALTER autonomous_execution_intent：execution_slice_id ──────────────
        col_slice_exists = await _column_exists(
            conn, "autonomous_execution_intent", "execution_slice_id"
        )
        if col_slice_exists:
            print(
                "  ⏭  autonomous_execution_intent.execution_slice_id — already exists, skipped"
            )
        else:
            await conn.execute(text(MYSQL_ALTER_INTENT_SLICE_ID))
            print("  ✅ autonomous_execution_intent.execution_slice_id — added")

    print("[Upgrade] V10.4.4 migration completed ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Rollback
# ─────────────────────────────────────────────────────────────────────────────


async def rollback() -> None:
    from sqlalchemy import text

    engine = await _get_engine()
    is_mysql = await _is_mysql(engine)
    if not is_mysql:
        print("[Rollback] ERROR — non-MySQL database.")
        sys.exit(1)

    print(
        "[Rollback] WARNING: This will drop 3 tables and remove 2 columns from autonomous_execution_intent."
    )
    confirm = input("Type 'yes' to confirm rollback: ").strip()
    if confirm != "yes":
        print("[Rollback] Aborted.")
        return

    async with engine.begin() as conn:
        # 先删除依赖表，再删 positions
        for stmt in ROLLBACK_DROP_TABLES:
            await conn.execute(text(stmt))
            print(f"  ✅ {stmt.strip()}")

        # 回滚 ALTER — 先删 index，再 DROP COLUMN（忽略不存在的错误）
        for stmt in ROLLBACK_ALTER_INTENT:
            try:
                await conn.execute(text(stmt))
                print(f"  ✅ {stmt.strip()}")
            except Exception as e:
                print(f"  ⚠  {stmt.strip()} — {e} (ignored)")

    print("[Rollback] V10.4.4 rollback completed ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V10.4.4 DB Migration")
    parser.add_argument("--check", action="store_true", help="检查表和列是否存在")
    parser.add_argument(
        "--rollback", action="store_true", help="回滚（删除新增表和列，危险！）"
    )
    args = parser.parse_args()

    if args.check:
        asyncio.run(check())
    elif args.rollback:
        asyncio.run(rollback())
    else:
        asyncio.run(upgrade())
