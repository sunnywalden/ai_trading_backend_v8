"""migration: 为 trade_attribution_entries 表添加 traded_at 列，并回填现有记录。

traded_at = 交易实际平仓日期（来自 trade_journal.exit_date）
这样归因记录的时间过滤按「交易发生时间」而非「入库时间」计算，
修复按 7天/30天 筛选时看不到数据的问题。
"""
import asyncio
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/Users/admin/IdeaProjects/ai_trading_backend_v8")

import app.models.strategy  # noqa: F401 — 触发 mapper 注册
from sqlalchemy import text, select
from app.models.db import Base, SessionLocal
from app.models.trade_attribution import TradeAttributionEntry
from app.models.trade_journal import TradeJournal


async def add_traded_at_column() -> bool:
    """检查并添加 traded_at 列（如已存在则跳过）。"""
    async with SessionLocal() as db:
        # 检查列是否已存在
        result = await db.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "  AND table_name = 'trade_attribution_entries' "
            "  AND column_name = 'traded_at'"
        ))
        exists = result.scalar() or 0
        if exists:
            print("[migration] traded_at 列已存在，跳过 ALTER TABLE")
            return False

        print("[migration] 添加 traded_at 列 ...")
        await db.execute(text(
            "ALTER TABLE trade_attribution_entries "
            "ADD COLUMN traded_at DATETIME NULL DEFAULT NULL "
            "COMMENT '交易实际平仓时间（来自 journal.exit_date）'"
        ))
        await db.commit()
        print("[migration] ALTER TABLE 完成")
        return True


async def backfill_traded_at() -> int:
    """为现有 25 条归因记录补填 traded_at（通过 notes 字段里的 journal_id 关联）。"""
    async with SessionLocal() as db:
        # 取所有 traded_at 为 NULL 的归因记录
        rows = list((await db.execute(
            select(TradeAttributionEntry)
            .where(TradeAttributionEntry.traded_at.is_(None))
        )).scalars().all())

        if not rows:
            print("[backfill] 所有记录 traded_at 已有值，无需回填")
            return 0

        print(f"[backfill] 待回填记录数: {len(rows)}")

        # 从 notes 字段中提取 journal_id
        j_id_pattern = re.compile(r"\[BACKFILL_FROM_JOURNAL\] journal_id=(\d+)")
        updated = 0

        for entry in rows:
            notes = getattr(entry, "notes", None) or ""
            m = j_id_pattern.search(notes)
            if not m:
                # 没有关联 journal_id，跳过
                continue

            journal_id = int(m.group(1))
            journal = await db.get(TradeJournal, journal_id)
            if journal is None:
                continue

            exit_date = getattr(journal, "exit_date", None)
            entry_date = getattr(journal, "entry_date", None)
            trade_date = exit_date or entry_date

            if trade_date is None:
                # 实在没日期，用 journal.created_at
                trade_date_dt = getattr(journal, "created_at", None)
            else:
                try:
                    from datetime import date as _date
                    if isinstance(trade_date, _date):
                        trade_date_dt = datetime(
                            trade_date.year, trade_date.month, trade_date.day,
                            tzinfo=timezone.utc,
                        )
                    elif isinstance(trade_date, datetime):
                        trade_date_dt = trade_date
                    else:
                        trade_date_dt = None
                except Exception:
                    trade_date_dt = None

            if trade_date_dt is not None:
                entry.traded_at = trade_date_dt
                updated += 1
                print(f"  entry.id={entry.id} {entry.symbol} traded_at={trade_date_dt.date()} (journal_id={journal_id})")

        if updated > 0:
            await db.commit()
            print(f"[backfill] 已更新 {updated} 条记录 traded_at")
        else:
            print("[backfill] 没有找到可回填的记录")

        return updated


async def verify() -> None:
    """验证修复效果：打印各时间窗口的归因记录计数。"""
    from datetime import timedelta
    async with SessionLocal() as db:
        from sqlalchemy import func
        for days in [7, 14, 30]:
            since = datetime.now(tz=timezone.utc) - timedelta(days=days)
            effective_date = func.coalesce(TradeAttributionEntry.traded_at, TradeAttributionEntry.created_at)
            cnt = (await db.execute(
                select(func.count()).select_from(TradeAttributionEntry)
                .where(effective_date >= since)
            )).scalar() or 0
            print(f"  [{days}天] attribution_count={cnt}")


async def main():
    added = await add_traded_at_column()
    updated = await backfill_traded_at()
    print("\n=== 验证：各时间窗口归因记录数 ===")
    await verify()
    print(f"\n完成: 新加列={added}, 回填记录数={updated}")


if __name__ == "__main__":
    asyncio.run(main())
