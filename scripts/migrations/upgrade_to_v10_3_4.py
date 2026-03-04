#!/usr/bin/env python3
"""upgrade_to_v10_3_4.py — V10.3.4 数据库迁移脚本

差异对比（v10.3.2 → v10.3.4）：

  v10.3.3（已有脚本：upgrade_to_v10_3_3.py，需先执行）
  ─────────────────────────────────────────────────────
  1. execution_quality_log            IS 四分解执行质量日志
  2. portfolio_factor_exposure         五因子敞口快照
  3. agent_communication_log          多智能体通信日志
  4. confidence_calibration_snapshot  置信度校准快照
  5. decision_post_mortems            决策事后剖析
  6. signal_weight_history            Kalman 信号权重演化历史

  v10.3.4（本脚本）
  ─────────────────────────────────────────────────────
  1. market_universe_symbols          机会扫描本地全量股票池（US/HK）

用法：
  # 在项目根目录执行
  cd /path/to/ai_trading_backend_v8

  # 检查是否已执行 v10.3.3
  python scripts/migrations/upgrade_to_v10_3_3.py  # 如未执行先跑此步

  # 执行 v10.3.4 迁移
  python scripts/migrations/upgrade_to_v10_3_4.py

  # 仅检查状态
  python scripts/migrations/upgrade_to_v10_3_4.py --check

  # 回滚（删除 market_universe_symbols 表）
  python scripts/migrations/upgrade_to_v10_3_4.py --rollback

  # 升级后记录版本
  python scripts/migrations/version_manager.py --record v10.3.3 \\
      --description "V10.3.3 新增6张分析表" --script "upgrade_to_v10_3_3.py"
  python scripts/migrations/version_manager.py --record v10.3.4 \\
      --description "V10.3.4 新增市场全量股票池表" --script "upgrade_to_v10_3_4.py"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


async def _get_engine():
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = settings.DATABASE_URL
    kwargs: dict = {"echo": False}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(db_url, **kwargs)


# ── DDL ───────────────────────────────────────────────────────────────────────

MYSQL_UP = """
CREATE TABLE IF NOT EXISTS market_universe_symbols (
    id              INT             NOT NULL AUTO_INCREMENT,
    symbol          VARCHAR(32)     NOT NULL COMMENT '股票代码，如 AAPL / 00700',
    market          VARCHAR(8)      NOT NULL COMMENT '市场：US / HK',
    name            VARCHAR(256)    NULL     COMMENT '股票名称（可选）',
    source          VARCHAR(32)     NOT NULL DEFAULT 'tiger' COMMENT '数据来源，如 tiger',
    is_active       TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '是否活跃（0=退市/已移除）',
    last_synced_at  DATETIME        NULL     COMMENT '最后一次同步时间（UTC）',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_market_universe_symbol (market, symbol),
    INDEX ix_market_universe_market_active (market, is_active),
    INDEX ix_market_universe_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='机会扫描本地全量股票池 V10.3.4';
"""

SQLITE_UP = """
CREATE TABLE IF NOT EXISTS market_universe_symbols (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    market         TEXT    NOT NULL,
    name           TEXT,
    source         TEXT    NOT NULL DEFAULT 'tiger',
    is_active      INTEGER NOT NULL DEFAULT 1,
    last_synced_at DATETIME,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SQLITE_UP_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_market_universe_symbol ON market_universe_symbols (market, symbol);",
    "CREATE INDEX IF NOT EXISTS ix_market_universe_market_active ON market_universe_symbols (market, is_active);",
    "CREATE INDEX IF NOT EXISTS ix_market_universe_symbol ON market_universe_symbols (symbol);",
]

ROLLBACK_DOWN = "DROP TABLE IF EXISTS market_universe_symbols;"

# ── 检查 SQL ──────────────────────────────────────────────────────────────────

MYSQL_CHECK = """
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name = 'market_universe_symbols';
"""

SQLITE_CHECK = """
SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='market_universe_symbols';
"""

# ── 前置依赖检查：v10.3.3 的其中一张表 ─────────────────────────────────────────

MYSQL_PREREQ_CHECK = """
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name = 'execution_quality_log';
"""

SQLITE_PREREQ_CHECK = """
SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='execution_quality_log';
"""


# ── 执行函数 ──────────────────────────────────────────────────────────────────

async def check_status(engine, is_mysql: bool) -> bool:
    """检查 market_universe_symbols 是否已存在，返回 True=已存在。"""
    from sqlalchemy import text
    q = MYSQL_CHECK if is_mysql else SQLITE_CHECK
    async with engine.connect() as conn:
        result = await conn.execute(text(q))
        exists = result.scalar() > 0
    status = "✅ 已存在" if exists else "❌ 不存在"
    print(f"  {status} — market_universe_symbols 表")
    return exists


async def check_prereq(engine, is_mysql: bool) -> bool:
    """检查 v10.3.3 是否已执行（以 execution_quality_log 为代表）。"""
    from sqlalchemy import text
    q = MYSQL_PREREQ_CHECK if is_mysql else SQLITE_PREREQ_CHECK
    async with engine.connect() as conn:
        result = await conn.execute(text(q))
        exists = result.scalar() > 0
    return exists


async def upgrade(engine, is_mysql: bool) -> None:
    from sqlalchemy import text

    print("─── 检查前置依赖（v10.3.3）───")
    prereq = await check_prereq(engine, is_mysql)
    if not prereq:
        print("⚠️  未检测到 v10.3.3 的表（execution_quality_log）。")
        print("   请先执行：python scripts/migrations/upgrade_to_v10_3_3.py")
        ans = input("   是否仍然继续执行 v10.3.4？(yes/N): ").strip().lower()
        if ans != "yes":
            print("已取消。")
            return
    else:
        print("  ✅ v10.3.3 前置依赖确认")

    print("\n─── 检查当前状态 ───")
    already = await check_status(engine, is_mysql)
    if already:
        print("ℹ️  market_universe_symbols 已存在，无需重复执行。")
        return

    print("\n─── 创建 market_universe_symbols 表 ───")
    async with engine.begin() as conn:
        if is_mysql:
            await conn.execute(text(MYSQL_UP.strip()))
            print("  ✅ market_universe_symbols（MySQL）")
        else:
            await conn.execute(text(SQLITE_UP.strip()))
            for idx_sql in SQLITE_UP_INDEXES:
                await conn.execute(text(idx_sql.strip()))
            print("  ✅ market_universe_symbols（SQLite）")

    print("\n✅ V10.3.4 迁移完成！")
    print("\n建议执行（记录版本）：")
    print("  python scripts/migrations/version_manager.py --record v10.3.4 \\")
    print('      --description "V10.3.4 新增市场全量股票池表" --script "upgrade_to_v10_3_4.py"')


async def rollback(engine) -> None:
    from sqlalchemy import text
    ans = input("⚠️  确认删除 market_universe_symbols 表？(yes/N): ").strip().lower()
    if ans != "yes":
        print("已取消回滚。")
        return
    async with engine.begin() as conn:
        await conn.execute(text(ROLLBACK_DOWN))
    print("✅ market_universe_symbols 已删除（已回滚到 v10.3.3）。")


async def main() -> None:
    parser = argparse.ArgumentParser(description="V10.3.4 数据库迁移")
    parser.add_argument("--check",    action="store_true", help="仅检查表状态")
    parser.add_argument("--rollback", action="store_true", help="回滚（删除表）")
    args = parser.parse_args()

    engine = await _get_engine()
    db_url = str(engine.url)
    is_mysql = "mysql" in db_url

    print("=" * 60)
    print("V10.3.4 数据库迁移")
    print("=" * 60)
    print(f"📦 数据库类型: {'MySQL' if is_mysql else 'SQLite'}")
    print(f"🔗 连接: {db_url[:60]}...\n")

    if args.check:
        print("🔍 检查迁移状态：")
        await check_status(engine, is_mysql)
    elif args.rollback:
        await rollback(engine)
    else:
        await upgrade(engine, is_mysql)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
