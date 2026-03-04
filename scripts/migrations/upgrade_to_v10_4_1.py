#!/usr/bin/env python3
"""upgrade_to_v10_4_1.py — V10.4.1 数据库迁移脚本

差异对比（v10.3.4 → v10.4.1）：

  v10.4.1（本脚本）
  ─────────────────────────────────────────────────────
  1. llm_call_log   LLM 调用全量日志（M1 T1.5）

用法：
  cd /path/to/ai_trading_backend_v8
  python scripts/migrations/upgrade_to_v10_4_1.py
  python scripts/migrations/upgrade_to_v10_4_1.py --check
  python scripts/migrations/upgrade_to_v10_4_1.py --rollback
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MYSQL_UP = """
CREATE TABLE IF NOT EXISTS llm_call_log (
    id                 BIGINT       NOT NULL AUTO_INCREMENT  COMMENT '主键',
    call_id            VARCHAR(36)  NOT NULL                 COMMENT 'UUID',
    caller             VARCHAR(64)  NOT NULL                 COMMENT '调用方服务名',
    model              VARCHAR(64)  NOT NULL                 COMMENT '使用的模型',
    prompt_tokens      INT          NULL                     COMMENT '输入 token 数',
    completion_tokens  INT          NULL                     COMMENT '输出 token 数',
    latency_ms         INT          NULL                     COMMENT '调用耗时(ms)',
    status             VARCHAR(16)  NOT NULL DEFAULT 'SUCCESS' COMMENT 'SUCCESS/TIMEOUT/RATE_LIMITED/ERROR',
    degraded           TINYINT(1)   NOT NULL DEFAULT 0       COMMENT '是否降级响应',
    error_msg          TEXT         NULL                     COMMENT '错误信息',
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '调用时间',
    PRIMARY KEY (id),
    INDEX idx_call_id  (call_id),
    INDEX idx_created  (created_at),
    INDEX idx_status   (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='LLM 调用全量日志';
"""

SQLITE_UP = """
CREATE TABLE IF NOT EXISTS llm_call_log (
    id                 INTEGER      PRIMARY KEY AUTOINCREMENT,
    call_id            TEXT         NOT NULL,
    caller             TEXT         NOT NULL,
    model              TEXT         NOT NULL,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    latency_ms         INTEGER,
    status             TEXT         NOT NULL DEFAULT 'SUCCESS',
    degraded           INTEGER      NOT NULL DEFAULT 0,
    error_msg          TEXT,
    created_at         TEXT         NOT NULL DEFAULT (datetime('now'))
);
"""

SQLITE_UP_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_llm_call_id  ON llm_call_log(call_id);",
    "CREATE INDEX IF NOT EXISTS idx_llm_created  ON llm_call_log(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_llm_status   ON llm_call_log(status);",
]

ROLLBACK_DOWN = "DROP TABLE IF EXISTS llm_call_log;"


async def _get_engine():
    from app.models.db import engine
    return engine


async def check_prereq(engine, is_mysql: bool) -> bool:
    from sqlalchemy import text
    tbl = "market_universe_symbols" if is_mysql else "market_universe_symbols"
    try:
        async with engine.connect() as conn:
            if is_mysql:
                r = await conn.execute(text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = :t"
                ), {"t": tbl})
            else:
                r = await conn.execute(text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:t"
                ), {"t": tbl})
            return (r.scalar() or 0) > 0
    except Exception:
        return False


async def check_status(engine, is_mysql: bool) -> bool:
    from sqlalchemy import text
    try:
        async with engine.connect() as conn:
            if is_mysql:
                r = await conn.execute(text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = 'llm_call_log'"
                ))
            else:
                r = await conn.execute(text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='llm_call_log'"
                ))
            exists = (r.scalar() or 0) > 0
    except Exception:
        exists = False

    if exists:
        print("  ✅ llm_call_log：已存在")
    else:
        print("  ❌ llm_call_log：不存在")
    return exists


async def upgrade(engine, is_mysql: bool) -> None:
    from sqlalchemy import text

    print("─── 检查前置依赖（v10.3.4）───")
    prereq = await check_prereq(engine, is_mysql)
    if not prereq:
        print("⚠️  未检测到 v10.3.4 的表（market_universe_symbols）。")
        print("   请先执行：python scripts/migrations/upgrade_to_v10_3_4.py")
        ans = input("   是否仍然继续执行 v10.4.1？(yes/N): ").strip().lower()
        if ans != "yes":
            print("已取消。")
            return
    else:
        print("  ✅ v10.3.4 前置依赖确认")

    print("\n─── 检查当前状态 ───")
    already = await check_status(engine, is_mysql)
    if already:
        print("ℹ️  llm_call_log 已存在，无需重复执行。")
        return

    print("\n─── 创建 llm_call_log 表 ───")
    async with engine.begin() as conn:
        if is_mysql:
            await conn.execute(text(MYSQL_UP.strip()))
            print("  ✅ llm_call_log（MySQL）")
        else:
            await conn.execute(text(SQLITE_UP.strip()))
            for idx_sql in SQLITE_UP_INDEXES:
                await conn.execute(text(idx_sql.strip()))
            print("  ✅ llm_call_log（SQLite）")

    print("\n✅ V10.4.1 迁移完成！")
    print("\n建议执行（记录版本）：")
    print("  python scripts/migrations/version_manager.py --record v10.4.1 \\")
    print('      --description "V10.4.1 新增 LLM 调用日志表" --script "upgrade_to_v10_4_1.py"')


async def rollback(engine) -> None:
    from sqlalchemy import text
    ans = input("⚠️  确认删除 llm_call_log 表？(yes/N): ").strip().lower()
    if ans != "yes":
        print("已取消回滚。")
        return
    async with engine.begin() as conn:
        await conn.execute(text(ROLLBACK_DOWN))
    print("✅ llm_call_log 已删除（已回滚）。")


async def main() -> None:
    parser = argparse.ArgumentParser(description="V10.4.1 数据库迁移")
    parser.add_argument("--check",    action="store_true", help="仅检查表状态")
    parser.add_argument("--rollback", action="store_true", help="回滚（删除表）")
    args = parser.parse_args()

    engine = await _get_engine()
    db_url = str(engine.url)
    is_mysql = "mysql" in db_url

    print("=" * 60)
    print("V10.4.1 数据库迁移")
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
