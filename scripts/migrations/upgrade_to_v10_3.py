#!/usr/bin/env python3
"""V10.3 交易可观测性：数据库升级迁移脚本

变更内容：
  1. trading_plan 表新增 10 个列（direction/confidence/reasoning/autonomy_action/
     source/pipeline_stage/stage_entered_at/stage_history/provenance_snapshot/
     position_fsm_state）
  2. 新建 fsm_transition_log 表（Plan FSM + Position FSM 转换事件日志）

支持 MySQL 8.0 和 SQLite（开发/测试环境）。
支持 --rollback 回滚，--check 仅检查。

使用：
    python scripts/migrations/upgrade_to_v10_3.py
    python scripts/migrations/upgrade_to_v10_3.py --rollback
    python scripts/migrations/upgrade_to_v10_3.py --check
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.models.trading_plan import TradingPlan

TRADING_PLAN_TABLE = TradingPlan.__tablename__


async def get_db_engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    db_url = settings.DATABASE_URL
    kwargs: dict = {"echo": False}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(db_url, **kwargs)


# ── MySQL DDL ─────────────────────────────────────────────────────────────────
# MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，每列单独执行并忽略「已存在」错误
MYSQL_UP_ALTER_COLUMNS: list[tuple[str, str]] = [
    # (column_name, ADD COLUMN sql)
    ("direction",          f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN direction VARCHAR(4) COMMENT '交易方向 BUY/SELL'"),
    ("confidence",         f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN confidence DECIMAL(5,2) COMMENT 'AI置信度 0-100'"),
    ("reasoning",          f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN reasoning TEXT COMMENT 'AI决策摘要'"),
    ("autonomy_action",    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN autonomy_action VARCHAR(20) COMMENT 'AUTO_EXECUTE/PENDING_CONFIRM'"),
    ("source",             f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN source VARCHAR(20) COMMENT 'AI_AUTONOMOUS/AI_ADVISORY/MANUAL'"),
    ("pipeline_stage",     f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN pipeline_stage SMALLINT COMMENT '当前Pipeline阶段 0-16'"),
    ("stage_entered_at",   f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN stage_entered_at DATETIME COMMENT '进入当前阶段时间'"),
    ("stage_history",      f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN stage_history JSON COMMENT '[{{stage,entered_at,exited_at}}]'"),
    ("provenance_snapshot",f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN provenance_snapshot JSON COMMENT '{{six_dim_scores,regime,risk_gate_results}}'"),
    ("position_fsm_state", f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN position_fsm_state VARCHAR(20) COMMENT '关联持仓最新FSM状态'"),
]

MYSQL_UP_STATEMENTS: list[str] = [
    # ── 新增索引（忽略已存在） ───────────────────────────────────────────────
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD INDEX idx_plan_pipeline_stage (pipeline_stage)",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD INDEX idx_plan_direction (direction)",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD INDEX idx_plan_source (source)",
    # ── fsm_transition_log 新表 ──────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS fsm_transition_log (
        id             INT AUTO_INCREMENT PRIMARY KEY,
        plan_id        INT          NOT NULL,
        fsm_type       VARCHAR(10)  NOT NULL COMMENT 'PLAN / POSITION',
        from_state     VARCHAR(32)  COMMENT '转换前状态',
        to_state       VARCHAR(32)  NOT NULL COMMENT '转换后状态',
        engine         VARCHAR(32)  COMMENT '触发引擎: scale_in/scale_out/trailing/manual',
        qty_delta      DECIMAL(10,4) COMMENT '数量变化（加减仓时）',
        trigger_reason TEXT         COMMENT '触发原因描述',
        occurred_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_fsm_plan_id     (plan_id),
        INDEX idx_fsm_type        (fsm_type),
        INDEX idx_fsm_occurred_at (occurred_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='V10.3 FSM状态转换事件日志';
    """,
]

MYSQL_DOWN_STATEMENTS: list[str] = [
    "DROP TABLE IF EXISTS fsm_transition_log;",
    """
    ALTER TABLE {table_name}
        DROP COLUMN IF EXISTS direction,
        DROP COLUMN IF EXISTS confidence,
        DROP COLUMN IF EXISTS reasoning,
        DROP COLUMN IF EXISTS autonomy_action,
        DROP COLUMN IF EXISTS source,
        DROP COLUMN IF EXISTS pipeline_stage,
        DROP COLUMN IF EXISTS stage_entered_at,
        DROP COLUMN IF EXISTS stage_history,
        DROP COLUMN IF EXISTS provenance_snapshot,
        DROP COLUMN IF EXISTS position_fsm_state;
    """.format(table_name=TRADING_PLAN_TABLE),
]

# ── SQLite DDL ────────────────────────────────────────────────────────────────
# SQLite 不支持 ADD COLUMN IF NOT EXISTS，需逐列执行
SQLITE_UP_STATEMENTS: list[str] = [
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN direction          VARCHAR(4);",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN confidence         DECIMAL(5,2);",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN reasoning          TEXT;",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN autonomy_action    VARCHAR(20);",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN source             VARCHAR(20);",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN pipeline_stage     SMALLINT;",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN stage_entered_at   DATETIME;",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN stage_history      JSON;",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN provenance_snapshot JSON;",
    f"ALTER TABLE {TRADING_PLAN_TABLE} ADD COLUMN position_fsm_state VARCHAR(20);",
    """
    CREATE TABLE IF NOT EXISTS fsm_transition_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id        INTEGER  NOT NULL,
        fsm_type       TEXT     NOT NULL,
        from_state     TEXT,
        to_state       TEXT     NOT NULL,
        engine         TEXT,
        qty_delta      REAL,
        trigger_reason TEXT,
        occurred_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_fsm_plan_id ON fsm_transition_log (plan_id);",
    "CREATE INDEX IF NOT EXISTS idx_fsm_occurred_at ON fsm_transition_log (occurred_at);",
]

SQLITE_DOWN_STATEMENTS: list[str] = [
    "DROP TABLE IF EXISTS fsm_transition_log;",
    # SQLite 不支持 DROP COLUMN，忽略（开发环境可重建 DB）
]

# ── CHECK QUERIES ─────────────────────────────────────────────────────────────
MYSQL_CHECK_QUERIES = [
    ("trading_plan.pipeline_stage 列",
     "SELECT COUNT(*) FROM information_schema.columns "
    f"WHERE table_schema=DATABASE() AND table_name='{TRADING_PLAN_TABLE}' "
    "AND column_name='pipeline_stage';"),
    ("fsm_transition_log 表",
     "SELECT COUNT(*) FROM information_schema.tables "
     "WHERE table_schema=DATABASE() AND table_name='fsm_transition_log';"),
]

SQLITE_CHECK_QUERIES = [
    ("fsm_transition_log 表",
     "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='fsm_transition_log';"),
]


# ── 执行逻辑 ──────────────────────────────────────────────────────────────────
async def run_alter_columns_mysql(engine, columns: list[tuple[str, str]]) -> None:
    """逐列执行 ALTER TABLE，忽略「列已存在（errno 1060）」错误。"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        for col_name, sql in columns:
            try:
                await conn.execute(text(sql.strip()))
                print(f"  ✅ 添加列 {col_name}")
            except Exception as e:
                err_str = str(e)
                if "1060" in err_str or "Duplicate column" in err_str.lower():
                    print(f"  ⏭  列 {col_name} 已存在，跳过")
                else:
                    raise
    print()


async def run_index_ignore_dup(engine, statements: list[str]) -> None:
    """执行 DDL 语句，忽略「索引已存在（errno 1061）」和重复键错误。"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        for stmt in statements:
            stmt_strip = stmt.strip()
            if not stmt_strip:
                continue
            try:
                await conn.execute(text(stmt_strip))
                print(f"  ✅ {stmt_strip[:60].replace(chr(10), ' ')}")
            except Exception as e:
                err_str = str(e)
                if any(x in err_str for x in ["1061", "Duplicate key name", "already exists"]):
                    print(f"  ⏭  已存在，跳过")
                else:
                    raise
    print()
async def run_statements(engine, statements: list[str], label: str) -> None:
    from sqlalchemy import text
    async with engine.begin() as conn:
        for i, stmt in enumerate(statements, 1):
            stmt_strip = stmt.strip()
            if not stmt_strip:
                continue
            print(f"  [{i}/{len(statements)}] {stmt_strip[:80].replace(chr(10), ' ')} ...")
            await conn.execute(text(stmt_strip))
    print(f"✅ {label} 完成\n")


async def run_sqlite_statements_ignore_dup(engine, statements: list[str]) -> None:
    """SQLite ALTER TABLE 逐句执行，忽略「table already has column」错误。"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        for stmt in statements:
            stmt_strip = stmt.strip()
            if not stmt_strip:
                continue
            try:
                await conn.execute(text(stmt_strip))
                print(f"  ✅ {stmt_strip[:70].replace(chr(10), ' ')}")
            except Exception as e:
                err_str = str(e).lower()
                if "duplicate column" in err_str or "already exists" in err_str:
                    print(f"  ⏭  已存在，跳过")
                else:
                    raise
    print()


async def run_check(engine, queries: list[tuple], is_mysql: bool) -> None:
    from sqlalchemy import text
    print("🔍 检查迁移状态：")
    async with engine.connect() as conn:
        for name, query in queries:
            result = await conn.execute(text(query))
            count = result.scalar()
            status = "✅ 已存在" if count else "❌ 不存在"
            print(f"  {status} — {name}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="V10.3 数据库迁移")
    parser.add_argument("--rollback", action="store_true", help="回滚迁移")
    parser.add_argument("--check",    action="store_true", help="仅检查状态")
    args = parser.parse_args()

    engine = await get_db_engine()
    db_url = str(engine.url)
    is_mysql = "mysql" in db_url

    print(f"📦 数据库类型: {'MySQL' if is_mysql else 'SQLite'}")
    print(f"🔗 连接: {db_url[:60]}...\n")

    if args.check:
        checks = MYSQL_CHECK_QUERIES if is_mysql else SQLITE_CHECK_QUERIES
        await run_check(engine, checks, is_mysql)
        await engine.dispose()
        return

    if args.rollback:
        stmts = MYSQL_DOWN_STATEMENTS if is_mysql else SQLITE_DOWN_STATEMENTS
        print("⏪ 开始回滚 V10.3 ...")
        await run_statements(engine, stmts, "回滚")
    else:
        print("🚀 开始升级 V10.3 ...")
        if is_mysql:
            print("─── Step 1: 添加 trading_plan 新列 ───")
            await run_alter_columns_mysql(engine, MYSQL_UP_ALTER_COLUMNS)
            print("─── Step 2: 添加索引 + 创建 fsm_transition_log 表 ───")
            await run_index_ignore_dup(engine, MYSQL_UP_STATEMENTS)
        else:
            print("─── SQLite: 逐列 ALTER TABLE + 建表 ───")
            await run_sqlite_statements_ignore_dup(engine, SQLITE_UP_STATEMENTS)

    print("🎉 V10.3 数据库迁移完成！")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
