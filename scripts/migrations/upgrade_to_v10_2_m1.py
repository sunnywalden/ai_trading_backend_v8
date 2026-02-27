"""V10.2-M1 Database Migration: Market Regime Intelligence Engine

新增内容：
  1. 新建表  market_regimes              — 体制历史记录（15 列）
  2. 修改表  autonomy_audit_log          — 添加 regime_at_decision / regime_confidence 两列
  3. 新建索引 idx_autonomy_regime        — 加速按体制筛选审计日志

用法：
    cd ai_trading_backend_v8
    python scripts/migrations/upgrade_to_v10_2_m1.py

回滚：
    python scripts/migrations/upgrade_to_v10_2_m1.py --rollback
"""
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ── 确保可以导入后端配置 ──────────────────────────────────────────────────────
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from app.core.config import settings  # noqa: E402


def _is_mysql() -> bool:
    return "mysql" in settings.DATABASE_URL.lower()


def _auto_inc_kw() -> str:
    return "AUTO_INCREMENT" if _is_mysql() else "AUTOINCREMENT"


async def upgrade() -> None:
    """正向迁移：升级到 V10.2-M1。"""
    print("🚀  开始数据库升级 → V10.2-M1 (Market Regime Intelligence Engine)")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # ──────────────────────────────────────────────────────────────────────
        # 步骤 1：创建 market_regimes 表
        # ──────────────────────────────────────────────────────────────────────
        print("\n  [1/3] 检查并创建 market_regimes 表 ...")
        auto_inc = _auto_inc_kw()

        if _is_mysql():
            create_market_regimes_sql = f"""
                CREATE TABLE IF NOT EXISTS market_regimes (
                    id                  INT          NOT NULL AUTO_INCREMENT,
                    classification_date DATETIME     NOT NULL COMMENT '体制被确认的日期时间（UTC）',
                    valid_from          DATETIME     NOT NULL COMMENT '体制生效开始时间',
                    valid_until         DATETIME     NULL     COMMENT '体制生效结束时间（NULL 表示当前仍有效）',
                    regime              VARCHAR(32)  NOT NULL COMMENT 'RegimeType枚举值，如 BULL_TREND',
                    prev_regime         VARCHAR(32)  NULL     COMMENT '前一个体制，首次为 NULL',
                    confidence          FLOAT        NOT NULL DEFAULT 0.0 COMMENT '分类置信度 [0,1]',
                    trend_score         FLOAT        NULL     COMMENT '趋势强度得分 [0,100]',
                    vol_score           FLOAT        NULL     COMMENT '波动率制度得分 [0,100]',
                    breadth_score       FLOAT        NULL     COMMENT '市场广度得分 [0,100]',
                    macro_score         FLOAT        NULL     COMMENT '宏观环境评分 [0,100]',
                    momentum_score      FLOAT        NULL     COMMENT '价格动量得分 [0,100]',
                    reasoning           TEXT         NULL     COMMENT '分类推理摘要',
                    is_override         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=管理员手动覆写',
                    override_by         VARCHAR(64)  NULL     COMMENT '覆写操作者账号',
                    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_market_regimes_date   (classification_date),
                    INDEX idx_market_regimes_regime (regime),
                    INDEX idx_market_regimes_valid  (valid_from, valid_until)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='市场体制历史表 V10.2-M1'
            """
        else:
            # SQLite
            create_market_regimes_sql = f"""
                CREATE TABLE IF NOT EXISTS market_regimes (
                    id                  INTEGER      PRIMARY KEY AUTOINCREMENT,
                    classification_date DATETIME     NOT NULL,
                    valid_from          DATETIME     NOT NULL,
                    valid_until         DATETIME     NULL,
                    regime              VARCHAR(32)  NOT NULL,
                    prev_regime         VARCHAR(32)  NULL,
                    confidence          REAL         NOT NULL DEFAULT 0.0,
                    trend_score         REAL         NULL,
                    vol_score           REAL         NULL,
                    breadth_score       REAL         NULL,
                    macro_score         REAL         NULL,
                    momentum_score      REAL         NULL,
                    reasoning           TEXT         NULL,
                    is_override         INTEGER      NOT NULL DEFAULT 0,
                    override_by         VARCHAR(64)  NULL,
                    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """

        await conn.execute(text(create_market_regimes_sql))
        print("      ✅  market_regimes 表已就绪")

        # SQLite 不在建表语句里支持多列 INDEX，需单独建
        if not _is_mysql():
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_market_regimes_date   ON market_regimes (classification_date)",
                "CREATE INDEX IF NOT EXISTS idx_market_regimes_regime ON market_regimes (regime)",
                "CREATE INDEX IF NOT EXISTS idx_market_regimes_valid  ON market_regimes (valid_from, valid_until)",
            ]:
                await conn.execute(text(idx_sql))
            print("      ✅  SQLite 索引已创建")

        # ──────────────────────────────────────────────────────────────────────
        # 步骤 2：为 autonomy_audit_log 添加 regime_at_decision 列
        # ──────────────────────────────────────────────────────────────────────
        print("\n  [2/3] 为 autonomy_audit_log 添加 regime_at_decision 列 ...")
        try:
            if _is_mysql():
                await conn.execute(text(
                    "ALTER TABLE autonomy_audit_log "
                    "ADD COLUMN regime_at_decision VARCHAR(32) NULL "
                    "COMMENT '决策时刻的市场体制' AFTER created_at"
                ))
            else:
                await conn.execute(text(
                    "ALTER TABLE autonomy_audit_log "
                    "ADD COLUMN regime_at_decision VARCHAR(32) NULL"
                ))
            print("      ✅  列 regime_at_decision 添加成功")
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate column name" in msg or "already exists" in msg or "1060" in msg:
                print("      ℹ️   列 regime_at_decision 已存在，跳过")
            else:
                raise

        # ──────────────────────────────────────────────────────────────────────
        # 步骤 3：为 autonomy_audit_log 添加 regime_confidence 列 + 索引
        # ──────────────────────────────────────────────────────────────────────
        print("\n  [3/3] 为 autonomy_audit_log 添加 regime_confidence 列及索引 ...")
        try:
            if _is_mysql():
                await conn.execute(text(
                    "ALTER TABLE autonomy_audit_log "
                    "ADD COLUMN regime_confidence FLOAT NULL "
                    "COMMENT '决策时刻体制置信度' AFTER regime_at_decision"
                ))
            else:
                await conn.execute(text(
                    "ALTER TABLE autonomy_audit_log "
                    "ADD COLUMN regime_confidence FLOAT NULL"
                ))
            print("      ✅  列 regime_confidence 添加成功")
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate column name" in msg or "already exists" in msg or "1060" in msg:
                print("      ℹ️   列 regime_confidence 已存在，跳过")
            else:
                raise

        # 创建体制索引（加速归因查询）
        try:
            if _is_mysql():
                await conn.execute(text(
                    "ALTER TABLE autonomy_audit_log "
                    "ADD INDEX idx_autonomy_regime (regime_at_decision)"
                ))
            else:
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_autonomy_regime "
                    "ON autonomy_audit_log (regime_at_decision)"
                ))
            print("      ✅  索引 idx_autonomy_regime 创建成功")
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate key name" in msg or "already exists" in msg or "1061" in msg:
                print("      ℹ️   索引 idx_autonomy_regime 已存在，跳过")
            else:
                raise

    await engine.dispose()
    print("\n🎉  V10.2-M1 数据库升级完成！")
    print("     新建表  : market_regimes")
    print("     修改表  : autonomy_audit_log (+2 列 +1 索引)")


async def rollback() -> None:
    """回滚：撤销 V10.2-M1 migration（⚠️ 会删除 market_regimes 全部数据）。"""
    print("⚠️   开始回滚 V10.2-M1 migration ...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # 1. 删除 market_regimes 表
        print("  [1/3] 删除 market_regimes 表 ...")
        await conn.execute(text("DROP TABLE IF EXISTS market_regimes"))
        print("      ✅  market_regimes 已删除")

        # 2. 删除 idx_autonomy_regime 索引
        print("  [2/3] 删除 idx_autonomy_regime 索引 ...")
        try:
            if _is_mysql():
                await conn.execute(text(
                    "ALTER TABLE autonomy_audit_log DROP INDEX idx_autonomy_regime"
                ))
            else:
                await conn.execute(text("DROP INDEX IF EXISTS idx_autonomy_regime"))
            print("      ✅  索引已删除")
        except Exception as exc:
            print(f"      ⚠️   索引删除失败（可忽略）: {exc}")

        # 3. SQLite 不支持 DROP COLUMN；MySQL 5.8+ 才支持；给出提示
        if _is_mysql():
            print("  [3/3] 从 autonomy_audit_log 删除两列 ...")
            try:
                await conn.execute(text(
                    "ALTER TABLE autonomy_audit_log "
                    "DROP COLUMN regime_at_decision, "
                    "DROP COLUMN regime_confidence"
                ))
                print("      ✅  列已删除")
            except Exception as exc:
                print(f"      ⚠️   列删除失败: {exc}")
        else:
            print(
                "  [3/3] SQLite 不支持 DROP COLUMN，"
                "请手动重建 autonomy_audit_log 表（或接受列存在）。"
            )

    await engine.dispose()
    print("\n🔄  V10.2-M1 roll-back 完成。")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="V10.2-M1 数据库迁移脚本")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="回滚本次 migration（⚠️ 会删除 market_regimes 表数据）",
    )
    args = parser.parse_args()

    if args.rollback:
        asyncio.run(rollback())
    else:
        asyncio.run(upgrade())
