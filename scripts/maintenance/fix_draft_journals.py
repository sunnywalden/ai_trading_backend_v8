#!/usr/bin/env python3
"""
scripts/maintenance/fix_draft_journals.py — 一次性修复存量 DRAFT 日志

问题背景：
  历史上 autonomous_engine 在 SELL/EXIT 信号执行时，
  总是创建新日志而不是关闭原 DRAFT 日志，导致：
  - 47 条 DRAFT 日志永远没有 exit_price
  - M1 backfill JOIN 永远找不到匹配 → TradingSignal.actual_return 全为 NULL

本脚本：
  步骤1: 找出所有 DRAFT 日志（exit_price=NULL, entry_price 有值）
  步骤2: 在同 account+symbol 维度，查找已执行的 EXIT/SELL TradingSignal
  步骤3: 将 exit_price 写入 DRAFT → 状态改为 CLOSED
  步骤4: 触发 M1 backfill → 回填 actual_return
  步骤5: 触发归因回填 → TradeAttributionEntry 写入

用法：
    python scripts/maintenance/fix_draft_journals.py [--dry-run]
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import sys
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv


async def main():
    import os
    os.environ.setdefault("ENV", "production")

    from app.models.db import SessionLocal
    from app.models.trade_journal import TradeJournal
    from app.models.trading_signal import TradingSignal
    from sqlalchemy import select, update, text

    _EXIT_DIRS = frozenset({"SELL", "SHORT", "EXIT", "EXIT_FULL", "REDUCE", "CLOSE", "SELL_ALL"})
    _EXIT_DIRS_SQL = "('SELL','SHORT','EXIT','EXIT_FULL','REDUCE','CLOSE','SELL_ALL')"

    logger.info("=== Fix DRAFT Journals — %s ===", "DRY-RUN" if DRY_RUN else "LIVE")

    async with SessionLocal() as session:
        # ── 步骤1: 取所有 DRAFT 日志（有 entry_price，无 exit_price）──
        draft_rows = (await session.execute(text(
            "SELECT id, account_id, symbol, direction, entry_price, quantity "
            "FROM trade_journal "
            "WHERE journal_status = 'DRAFT' AND exit_price IS NULL AND entry_price IS NOT NULL "
            "ORDER BY created_at ASC LIMIT 500"
        ))).fetchall()

        logger.info("Found %d DRAFT journals to fix", len(draft_rows))

        closed_count = 0
        no_exit_sig = 0

        for jrow in draft_rows:
            j_id       = jrow[0]
            acc_id     = jrow[1]
            symbol     = jrow[2]
            direction  = jrow[3]
            entry_price = float(jrow[4] or 0)
            qty         = float(jrow[5] or 0)

            # ── 步骤2: 找同 account+symbol 的出场信号（有 executed_price）──
            exit_sig = (await session.execute(text(
                f"SELECT executed_price, executed_quantity, executed_at, signal_id "
                f"FROM trading_signals "
                f"WHERE account_id = :acc AND symbol = :sym "
                f"  AND direction IN {_EXIT_DIRS_SQL} "
                f"  AND executed_price IS NOT NULL "
                f"ORDER BY executed_at DESC LIMIT 1"
            ), {"acc": acc_id, "sym": symbol})).fetchone()

            if exit_sig is None or not exit_sig[0]:
                logger.debug(" [SKIP] journal_id=%d %s %s — no exit signal", j_id, acc_id, symbol)
                no_exit_sig += 1
                continue

            exit_price = float(exit_sig[0])
            exec_qty   = float(exit_sig[1] or qty or 1)
            exec_at    = exit_sig[2]
            exit_sig_id = exit_sig[3]

            used_qty = qty if qty > 0 else exec_qty
            direction_mul = -1.0 if (direction or "BUY").upper() in {"BUY", "LONG"} else 1.0
            realized_pnl = (exit_price - entry_price) * used_qty * direction_mul if entry_price > 0 else 0.0

            exec_date = None
            if exec_at:
                try:
                    exec_date = exec_at.date() if hasattr(exec_at, "date") else None
                except Exception:
                    pass
            if not exec_date:
                exec_date = date.today()

            logger.info(
                " [CLOSE] journal_id=%d %s %s: entry=%.4f exit=%.4f pnl=%.2f",
                j_id, acc_id, symbol, entry_price, exit_price, realized_pnl,
            )

            if not DRY_RUN:
                notes_append = f" | fix_script exit_signal={exit_sig_id}" if exit_sig_id else ""
                await session.execute(text(
                    "UPDATE trade_journal "
                    "SET exit_price=:ep, exit_date=:ed, realized_pnl=:pnl, "
                    "    journal_status='CLOSED', "
                    "    lesson_learned=CONCAT(COALESCE(lesson_learned,''),:note) "
                    "WHERE id=:jid"
                ), {"ep": exit_price, "ed": exec_date, "pnl": realized_pnl,
                    "note": notes_append, "jid": j_id})

            closed_count += 1

        if not DRY_RUN and closed_count > 0:
            await session.commit()
            logger.info("Committed %d journal closures", closed_count)
        else:
            logger.info("%s: would close %d journals",
                        "DRY-RUN" if DRY_RUN else "LIVE (0)", closed_count)

        logger.info("No exit signal found for %d draft journals (skipped)", no_exit_sig)

    # ── 步骤4: actual_return 回填（M1 JOIN SQL 路径）──
    if not DRY_RUN and closed_count > 0:
        logger.info("=== Triggering actual_return backfill (M1 JOIN path)... ===")
        async with SessionLocal() as session:
            null_before = (await session.execute(text(
                "SELECT COUNT(*) FROM trading_signals WHERE actual_return IS NULL"
            ))).scalar()
            logger.info("Signals missing actual_return BEFORE: %d", null_before or 0)

            res = await session.execute(text(
                """UPDATE trading_signals ts
                   JOIN trade_journal tj
                     ON ts.signal_id = tj.signal_id
                    AND tj.journal_status IN ('CLOSED','COMPLETED','DONE')
                    AND tj.exit_price  IS NOT NULL
                    AND tj.entry_price IS NOT NULL
                    AND tj.entry_price != 0
                   SET ts.actual_return = (tj.exit_price - tj.entry_price) / tj.entry_price,
                       ts.pnl_pct = CASE
                         WHEN tj.quantity IS NOT NULL AND tj.quantity != 0
                              AND tj.realized_pnl IS NOT NULL
                         THEN tj.realized_pnl / (ABS(tj.quantity) * tj.entry_price)
                         ELSE NULL END
                   WHERE ts.actual_return IS NULL"""
            ))
            await session.commit()
            logger.info("actual_return backfill: updated %d rows", getattr(res, "rowcount", -1))

            null_after = (await session.execute(text(
                "SELECT COUNT(*) FROM trading_signals WHERE actual_return IS NULL"
            ))).scalar()
            logger.info("Signals missing actual_return AFTER:  %d", null_after or 0)

        # ── 步骤5: 触发归因回填 ──
        logger.info("=== Triggering attribution backfill... ===")
        import importlib
        for mod in ["app.models.strategy", "app.models.trading_signal",
                    "app.models.trade_journal", "app.models.trade_attribution"]:
            try:
                importlib.import_module(mod)
            except Exception as e:
                logger.debug("import %s: %s", mod, e)

        from app.services.trade_attribution_engine import trade_attribution_engine
        async with SessionLocal() as session:
            result = await trade_attribution_engine.backfill_from_journal(
                session, days=None, limit=2000, dry_run=False
            )
        logger.info(
            "attribution backfill: processed=%d inserted=%d skipped=%d",
            result.get("processed", 0), result.get("inserted", 0), result.get("skipped_existing", 0),
        )

    logger.info("=== Done. closed=%d no_exit=%d dry_run=%s ===",
                closed_count, no_exit_sig, DRY_RUN)


if __name__ == "__main__":
    asyncio.run(main())
