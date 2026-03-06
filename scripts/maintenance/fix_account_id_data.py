#!/usr/bin/env python
"""
fix_account_id_data.py
─────────────────────────────────────────────────────────────────────────────
证券数据维度字段数据修复脚本  V10.3.3+

背景
────
将 5 张证券/交易数据表中存储的平台 user_id（如 "admin"、"system"）
替换为正确的券商账号（broker account_id），以匹配 user_id→account_id
列重命名迁移后的语义。

运行顺序
────────
1. 先执行 `scripts/sql/migrate_user_id_to_account_id.sql`（ALTER TABLE / 索引重命名）
2. 再执行本脚本修复历史数据

也可在 ALTER TABLE **之前** 执行本脚本（脚本会自动检测列名）。

使用场景
────────
  # 仅预览（默认 dry-run，不修改数据）
    python scripts/maintenance/fix_account_id_data.py

  # 实际执行
    python scripts/maintenance/fix_account_id_data.py --apply

  # 指定额外的用户→账号映射（覆盖自动检测）
    python scripts/maintenance/fix_account_id_data.py --apply --map admin=21272246230273657

修复策略
────────
表名                            策略
──────────────────────────────  ──────────────────────────────────────────────
signal_weight_history           有唯一约束(account_id,record_date,dimension)：
                                  ① broker 行已存在相同 key → DELETE 旧行
                                  ② broker 行不存在 → UPDATE 到 broker account
confidence_calibration_snapshot 有唯一约束(account_id,snapshot_date)：同上
portfolio_factor_exposure        无唯一约束 → UPDATE
execution_quality_log            无唯一约束 → 优先通过 intent_id JOIN
                                  autonomous_execution_intent 获取真实 account_id，
                                  无法 JOIN 时 fallback 到主账号
decision_post_mortems            无唯一约束 → UPDATE
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import asyncio
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 确保 PYTHONPATH 已包含项目根目录
import app.models.strategy  # noqa: F401 – 触发所有模型注册
from app.models.db import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fix_account_id")

# ─── 非 broker 账号的 user_id 集合（需要被替换的值）─────────────────────────
PLATFORM_USERS = {"admin", "system"}

# ─── 平台账号 → broker 账号的静态兜底映射（脚本自动构建后会覆盖）────────────
STATIC_FALLBACK: dict[str, str] = {
    "admin": "21272246230273657",
    "system": "21272246230273657",
}


# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

async def _col_name(db: AsyncSession, table: str) -> str:
    """返回表中账号列的当前名称（user_id 或 account_id）。"""
    for col in ("account_id", "user_id"):
        try:
            await db.execute(text(f"SELECT `{col}` FROM `{table}` LIMIT 0"))
            return col
        except Exception:
            pass
    raise RuntimeError(f"表 {table} 中既没有 account_id 也没有 user_id 列")


async def _build_mapping(db: AsyncSession, extra: dict[str, str]) -> dict[str, str]:
    """
    从 trading_signals 表构建 platform_user → broker_account 映射。
    取每个 user_id 最近一次关联的 broker account_id（最新优先）。
    """
    rows = (await db.execute(text(
        "SELECT user_id, account_id "
        "FROM ("
        "  SELECT user_id, account_id, "
        "         ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) rn "
        "  FROM trading_signals "
        "  WHERE account_id IS NOT NULL"
        ") t WHERE rn = 1"
    ))).all()

    mapping = STATIC_FALLBACK.copy()
    for r in rows:
        if r.user_id and r.account_id:
            mapping[r.user_id] = r.account_id

    # 命令行覆盖优先级最高
    mapping.update(extra)

    # 仅保留平台用户条目
    result = {k: v for k, v in mapping.items() if k in PLATFORM_USERS}
    log.info("用户→账号 映射: %s", result)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 各表修复逻辑
# ═══════════════════════════════════════════════════════════════════════════

async def fix_signal_weight_history(
    db: AsyncSession,
    mapping: dict[str, str],
    dry_run: bool,
) -> dict[str, int]:
    """
    signal_weight_history – UNIQUE(account_id, record_date, dimension)
    ① broker 行已存在（冲突） → DELETE 旧行
    ② broker 行不存在 → UPDATE account_id
    """
    col = await _col_name(db, "signal_weight_history")
    stats: dict[str, int] = {"deleted": 0, "updated": 0, "skipped": 0}

    for old_id, new_id in mapping.items():
        # 找出冲突行（broker 已有相同 record_date + dimension）
        conflict_ids = (await db.execute(text(
            f"SELECT old.id "
            f"FROM signal_weight_history old "
            f"JOIN signal_weight_history new_ "
            f"  ON old.record_date = new_.record_date "
            f" AND old.dimension   = new_.dimension "
            f"WHERE old.`{col}` = :old_id "
            f"  AND new_.`{col}` = :new_id"
        ), {"old_id": old_id, "new_id": new_id})).scalars().all()

        if conflict_ids:
            log.warning(
                "[signal_weight_history] %r与%r冲突 → 将DELETE %d旧行: ids=%s",
                old_id, new_id, len(conflict_ids), list(conflict_ids),
            )
            if not dry_run:
                await db.execute(text(
                    f"DELETE FROM signal_weight_history WHERE id IN :ids"
                ), {"ids": tuple(conflict_ids)})
            stats["deleted"] += len(conflict_ids)

        # 找出无冲突行 → UPDATE
        safe_ids = (await db.execute(text(
            f"SELECT swh.id "
            f"FROM signal_weight_history swh "
            f"WHERE swh.`{col}` = :old_id "
            f"  AND NOT EXISTS ("
            f"    SELECT 1 FROM signal_weight_history dup "
            f"    WHERE dup.`{col}` = :new_id "
            f"      AND dup.record_date = swh.record_date "
            f"      AND dup.dimension   = swh.dimension"
            f"  )"
        ), {"old_id": old_id, "new_id": new_id})).scalars().all()

        if safe_ids:
            log.info(
                "[signal_weight_history] %r→%r UPDATE %d行: ids=%s",
                old_id, new_id, len(safe_ids), list(safe_ids),
            )
            if not dry_run:
                await db.execute(text(
                    f"UPDATE signal_weight_history SET `{col}` = :new_id "
                    f"WHERE id IN :ids"
                ), {"new_id": new_id, "ids": tuple(safe_ids)})
            stats["updated"] += len(safe_ids)

    return stats


async def fix_confidence_calibration_snapshot(
    db: AsyncSession,
    mapping: dict[str, str],
    dry_run: bool,
) -> dict[str, int]:
    """
    confidence_calibration_snapshot – UNIQUE(account_id, snapshot_date)
    ① broker 行已存在 → DELETE 旧行
    ② broker 行不存在 → UPDATE
    """
    col = await _col_name(db, "confidence_calibration_snapshot")
    stats: dict[str, int] = {"deleted": 0, "updated": 0}

    for old_id, new_id in mapping.items():
        conflict_ids = (await db.execute(text(
            f"SELECT old.id "
            f"FROM confidence_calibration_snapshot old "
            f"JOIN confidence_calibration_snapshot new_ "
            f"  ON old.snapshot_date = new_.snapshot_date "
            f"WHERE old.`{col}` = :old_id "
            f"  AND new_.`{col}` = :new_id"
        ), {"old_id": old_id, "new_id": new_id})).scalars().all()

        if conflict_ids:
            log.warning(
                "[confidence_calibration_snapshot] %r与%r冲突 → DELETE %d旧行",
                old_id, new_id, len(conflict_ids),
            )
            if not dry_run:
                await db.execute(text(
                    "DELETE FROM confidence_calibration_snapshot WHERE id IN :ids"
                ), {"ids": tuple(conflict_ids)})
            stats["deleted"] += len(conflict_ids)

        safe_ids = (await db.execute(text(
            f"SELECT ccs.id "
            f"FROM confidence_calibration_snapshot ccs "
            f"WHERE ccs.`{col}` = :old_id "
            f"  AND NOT EXISTS ("
            f"    SELECT 1 FROM confidence_calibration_snapshot dup "
            f"    WHERE dup.`{col}` = :new_id "
            f"      AND dup.snapshot_date = ccs.snapshot_date"
            f"  )"
        ), {"old_id": old_id, "new_id": new_id})).scalars().all()

        if safe_ids:
            log.info(
                "[confidence_calibration_snapshot] %r→%r UPDATE %d行",
                old_id, new_id, len(safe_ids),
            )
            if not dry_run:
                await db.execute(text(
                    f"UPDATE confidence_calibration_snapshot SET `{col}` = :new_id "
                    f"WHERE id IN :ids"
                ), {"new_id": new_id, "ids": tuple(safe_ids)})
            stats["updated"] += len(safe_ids)

    return stats


async def fix_portfolio_factor_exposure(
    db: AsyncSession,
    mapping: dict[str, str],
    dry_run: bool,
) -> dict[str, int]:
    """
    portfolio_factor_exposure – 无唯一约束 → 直接 UPDATE
    """
    col = await _col_name(db, "portfolio_factor_exposure")
    stats: dict[str, int] = {"updated": 0}

    for old_id, new_id in mapping.items():
        cnt = (await db.execute(text(
            f"SELECT COUNT(*) FROM portfolio_factor_exposure WHERE `{col}` = :old_id"
        ), {"old_id": old_id})).scalar() or 0

        if cnt:
            log.info("[portfolio_factor_exposure] %r→%r UPDATE %d行", old_id, new_id, cnt)
            if not dry_run:
                await db.execute(text(
                    f"UPDATE portfolio_factor_exposure SET `{col}` = :new_id "
                    f"WHERE `{col}` = :old_id"
                ), {"new_id": new_id, "old_id": old_id})
            stats["updated"] += cnt

    return stats


async def fix_execution_quality_log(
    db: AsyncSession,
    mapping: dict[str, str],
    dry_run: bool,
) -> dict[str, int]:
    """
    execution_quality_log – 无唯一约束
    优先通过 intent_id → autonomous_execution_intent.account_id 精确更新；
    intent_id 为 NULL 或关联表不存在时退化为 mapping 兜底。
    """
    col = await _col_name(db, "execution_quality_log")
    stats: dict[str, int] = {"updated_via_intent": 0, "updated_fallback": 0}

    # ── 尝试 intent_id 精确路径 ────────────────────────────────────────────
    for old_id in mapping:
        try:
            # 检查 autonomous_execution_intent 表是否存在
            await db.execute(text(
                "SELECT id FROM autonomous_execution_intent LIMIT 0"
            ))
            has_aei = True
        except Exception:
            has_aei = False

        if has_aei:
            rows = (await db.execute(text(
                f"SELECT eql.id, aei.account_id "
                f"FROM execution_quality_log eql "
                f"JOIN autonomous_execution_intent aei ON aei.id = eql.intent_id "
                f"WHERE eql.`{col}` = :old_id "
                f"  AND aei.account_id IS NOT NULL"
            ), {"old_id": old_id})).all()

            # 按 account_id 分组批量更新
            grouped: dict[str, list[int]] = {}
            for row in rows:
                grouped.setdefault(row.account_id, []).append(row.id)

            for real_account, ids in grouped.items():
                log.info(
                    "[execution_quality_log] %r►%r (via intent) UPDATE %d行",
                    old_id, real_account, len(ids),
                )
                if not dry_run:
                    await db.execute(text(
                        f"UPDATE execution_quality_log SET `{col}` = :new_id "
                        f"WHERE id IN :ids"
                    ), {"new_id": real_account, "ids": tuple(ids)})
                stats["updated_via_intent"] += len(ids)

        # ── 兜底：intent_id 为 NULL 或 AEI 中查不到 account_id 的行 ──────
        if has_aei:
            fallback_ids = (await db.execute(text(
                f"SELECT eql.id FROM execution_quality_log eql "
                f"WHERE eql.`{col}` = :old_id "
                f"  AND (eql.intent_id IS NULL "
                f"       OR NOT EXISTS ("
                f"         SELECT 1 FROM autonomous_execution_intent aei "
                f"         WHERE aei.id = eql.intent_id "
                f"           AND aei.account_id IS NOT NULL"
                f"  ))"
            ), {"old_id": old_id})).scalars().all()
        else:
            fallback_ids = (await db.execute(text(
                f"SELECT id FROM execution_quality_log WHERE `{col}` = :old_id"
            ), {"old_id": old_id})).scalars().all()

        if fallback_ids:
            new_id = mapping[old_id]
            log.info(
                "[execution_quality_log] %r→%r (fallback, no intent) UPDATE %d行",
                old_id, new_id, len(fallback_ids),
            )
            if not dry_run:
                await db.execute(text(
                    f"UPDATE execution_quality_log SET `{col}` = :new_id "
                    f"WHERE id IN :ids"
                ), {"new_id": new_id, "ids": tuple(fallback_ids)})
            stats["updated_fallback"] += len(fallback_ids)

    return stats


async def fix_decision_post_mortems(
    db: AsyncSession,
    mapping: dict[str, str],
    dry_run: bool,
) -> dict[str, int]:
    """
    decision_post_mortems – 无唯一约束 → 直接 UPDATE
    """
    col = await _col_name(db, "decision_post_mortems")
    stats: dict[str, int] = {"updated": 0}

    for old_id, new_id in mapping.items():
        cnt = (await db.execute(text(
            f"SELECT COUNT(*) FROM decision_post_mortems WHERE `{col}` = :old_id"
        ), {"old_id": old_id})).scalar() or 0

        if cnt:
            log.info("[decision_post_mortems] %r→%r UPDATE %d行", old_id, new_id, cnt)
            if not dry_run:
                await db.execute(text(
                    f"UPDATE decision_post_mortems SET `{col}` = :new_id "
                    f"WHERE `{col}` = :old_id"
                ), {"new_id": new_id, "old_id": old_id})
            stats["updated"] += cnt

    return stats


# ═══════════════════════════════════════════════════════════════════════════
# 修复后验证
# ═══════════════════════════════════════════════════════════════════════════

async def verify(db: AsyncSession) -> None:
    """修复完成后，检查5张表中是否仍有平台 user_id 残留。"""
    tables = [
        "signal_weight_history",
        "portfolio_factor_exposure",
        "confidence_calibration_snapshot",
        "execution_quality_log",
        "decision_post_mortems",
    ]
    platform_ids_sql = ", ".join(f"'{u}'" for u in PLATFORM_USERS)

    log.info("\n─── 验证结果 ─────────────────────────────────────────────────")
    all_clean = True
    for tbl in tables:
        col = await _col_name(db, tbl)
        cnt = (await db.execute(text(
            f"SELECT COUNT(*) FROM `{tbl}` WHERE `{col}` IN ({platform_ids_sql})"
        ))).scalar() or 0
        if cnt:
            log.error("  ❌ %s: 仍有 %d 行使用平台 user_id", tbl, cnt)
            all_clean = False
        else:
            log.info("  ✅ %s: 无残留平台 user_id", tbl)

    if all_clean:
        log.info("✅ 全部通过 — 5张表已无平台 user_id 数据")
    else:
        log.warning("⚠️  验证未通过，请检查上方报错行")


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

async def run(apply: bool, extra_map: dict[str, str]) -> None:
    dry_run = not apply
    if dry_run:
        log.info("═══ DRY-RUN 模式（仅报告，不修改）— 加 --apply 执行修改 ═══")
    else:
        log.info("═══ APPLY 模式 — 将修改数据库 ═══")

    async with SessionLocal() as db:
        mapping = await _build_mapping(db, extra_map)

        results: dict[str, Any] = {}

        log.info("\n─── signal_weight_history ────")
        results["signal_weight_history"] = await fix_signal_weight_history(db, mapping, dry_run)

        log.info("\n─── confidence_calibration_snapshot ────")
        results["confidence_calibration_snapshot"] = await fix_confidence_calibration_snapshot(db, mapping, dry_run)

        log.info("\n─── portfolio_factor_exposure ────")
        results["portfolio_factor_exposure"] = await fix_portfolio_factor_exposure(db, mapping, dry_run)

        log.info("\n─── execution_quality_log ────")
        results["execution_quality_log"] = await fix_execution_quality_log(db, mapping, dry_run)

        log.info("\n─── decision_post_mortems ────")
        results["decision_post_mortems"] = await fix_decision_post_mortems(db, mapping, dry_run)

        if not dry_run:
            await db.commit()
            log.info("\n✅ 事务已提交")

        # 汇总
        log.info("\n─── 汇总 ──────────────────────────────────────────────────")
        for tbl, s in results.items():
            log.info("  %-40s  %s", tbl, s)

        if not dry_run:
            log.info("\n─── 修复后验证 ────")
            await verify(db)


def main() -> None:
    parser = argparse.ArgumentParser(description="修复5张证券数据表的account_id历史数据")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="实际执行修改（默认为 dry-run 预览）",
    )
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="手动指定映射，如 --map admin=21272246230273657（可多次传入）",
    )
    args = parser.parse_args()

    extra: dict[str, str] = {}
    for item in args.map:
        if "=" not in item:
            print(f"--map 参数格式错误（应为 OLD=NEW）: {item}", file=sys.stderr)
            sys.exit(1)
        old, new = item.split("=", 1)
        extra[old.strip()] = new.strip()

    asyncio.run(run(apply=args.apply, extra_map=extra))


if __name__ == "__main__":
    main()
