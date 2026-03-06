"""data_sync_jobs.py — V10.4 数据自动同步 Jobs

负责修复三条断裂的数据流：

Job ①  journal_auto_close_job  (每 30 分钟)
    扫描已执行 TradingSignal（出场方向），
    将对应的 DRAFT TradeJournal 写入 exit_price + status=CLOSED。
    同时修复 entry_price 缺失问题（从 TradingSignal.executed_price 补填）。

Job ②  signal_return_backfill_extra_job  (每 6 小时)
    是对 M1 return_backfill_job 的补充路径：
    当 TradeJournal 的 signal_id 已匹配 TradingSignal，
    且 journal 状态 CLOSED/COMPLETED 和 exit_price 有值 → 回填 actual_return。
    额外兜底：对于没有 signal_id 的旧 COMPLETED 日志，
    尝试通过 symbol+account+date 段匹配 TradingSignal 并回填。

Job ③  attribution_daily_backfill_job  (每天 23:30)
    将所有符合条件的 TradeJournal（已平仓）增量写入 TradeAttributionEntry，
    自动触发 IC 重算 (≥10 条时)。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Job ① : journal_auto_close_job
# ─────────────────────────────────────────────────────────────────────────────

# 出场方向集合（与 autonomous_engine 保持一致）
_EXIT_DIRS = frozenset({"SELL", "SHORT", "EXIT", "EXIT_FULL", "REDUCE", "CLOSE", "SELL_ALL"})

# 触发关闭 Journal 所需的 TradingSignal 状态
_EXECUTED_STATUSES = ("EXECUTED", "COMPLETED", "CLOSED", "DONE")


async def _do_journal_auto_close(session: AsyncSession) -> dict:
    """核心逻辑：找已执行的出场信号，关闭对应的 DRAFT 建仓日志。"""
    from app.models.trade_journal import TradeJournal  # noqa: 懒导入 — ORM 必须在 app 启动后注册
    from app.models.trading_signal import TradingSignal

    # 找已成交的出场信号（有 executed_price）
    exit_sigs = (await session.execute(
        select(
            TradingSignal.id,
            TradingSignal.signal_id,
            TradingSignal.account_id,
            TradingSignal.symbol,
            TradingSignal.direction,
            TradingSignal.executed_price,
            TradingSignal.executed_quantity,
            TradingSignal.executed_at,
        )
        .where(
            TradingSignal.direction.in_(list(_EXIT_DIRS)),
            TradingSignal.executed_price.isnot(None),
            TradingSignal.executed_at.isnot(None),
        )
        .order_by(TradingSignal.executed_at.asc())
        .limit(500)
    )).all()

    closed = 0
    entry_filled = 0

    for sig in exit_sigs:
        # 查找对应 DRAFT 建仓日志：同 account_id + symbol，尚未写 exit_price
        journal = (await session.execute(
            select(TradeJournal)
            .where(
                TradeJournal.account_id == sig.account_id,
                TradeJournal.symbol == sig.symbol,
                TradeJournal.journal_status == "DRAFT",
                TradeJournal.exit_price.is_(None),
                TradeJournal.entry_price.isnot(None),
            )
            .order_by(TradeJournal.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        if journal is None:
            continue

        exit_price = float(sig.executed_price)
        entry_price = float(getattr(journal, 'entry_price') or 0)
        used_qty = float(getattr(journal, 'quantity') or sig.executed_quantity or 0)
        direction_mul = -1.0 if str(getattr(journal, 'direction') or "BUY").upper() in {"BUY", "LONG"} else 1.0
        realized_pnl = (exit_price - entry_price) * used_qty * direction_mul if entry_price > 0 else 0.0

        exec_date: Optional[date] = None
        if sig.executed_at:
            try:
                exec_date = sig.executed_at.date() if hasattr(sig.executed_at, "date") else None
            except Exception:
                pass

        setattr(journal, 'exit_price', exit_price)
        setattr(journal, 'exit_date', exec_date or date.today())
        setattr(journal, 'realized_pnl', realized_pnl)
        setattr(journal, 'journal_status', "CLOSED")
        if sig.signal_id:
            notes = getattr(journal, 'lesson_learned') or ""
            setattr(journal, 'lesson_learned', (notes + f" | 平仓信号: {sig.signal_id}").strip(" |"))

        closed += 1

    # 补填 entry_price：DRAFT 日志中 entry_price=NULL 但 signal_id 匹配信号有 executed_price
    draft_no_entry = (await session.execute(
        select(TradeJournal)
        .where(
            TradeJournal.journal_status == "DRAFT",
            TradeJournal.entry_price.is_(None),
            TradeJournal.signal_id.isnot(None),
        )
        .limit(200)
    )).scalars().all()

    for j in draft_no_entry:
        sig_row = (await session.execute(
            select(TradingSignal.executed_price, TradingSignal.suggested_price)
            .where(TradingSignal.signal_id == j.signal_id)
            .limit(1)
        )).first()
        if sig_row is None:
            continue
        fill_price = sig_row.executed_price or sig_row.suggested_price
        if fill_price:
            setattr(j, 'entry_price', float(fill_price))
            entry_filled += 1

    if closed > 0 or entry_filled > 0:
        await session.commit()

    return {"closed": closed, "entry_filled": entry_filled}


async def journal_auto_close_job() -> None:
    """Job ①: 每 30 分钟 — 关闭与已执行出场信号匹配的 DRAFT 日志。"""
    from app.models.db import SessionLocal
    try:
        async with SessionLocal() as session:
            result = await _do_journal_auto_close(session)
        if result["closed"] > 0 or result["entry_filled"] > 0:
            logger.info(
                "[DataSync] journal_auto_close: closed=%d entry_filled=%d",
                result["closed"], result["entry_filled"],
            )
    except Exception as exc:
        logger.error("[DataSync] journal_auto_close_job FAILED: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Job ② : signal_return_backfill_extra_job
# ─────────────────────────────────────────────────────────────────────────────

async def _do_signal_return_backfill_extra(session: AsyncSession) -> int:
    """
    enhanced M1 backfill：
    Path A: 已有 signal_id 链路（CLOSED journal  + exit_price）→ 回填 actual_return
    Path B: 旧 COMPLETED 日志无 signal_id，但有 entry+exit+account+symbol →
            尝试按 account_id + symbol + date 段匹配 TradingSignal，写入 actual_return
    """
    from app.models.trade_journal import TradeJournal  # noqa: 懒导入
    from app.models.trading_signal import TradingSignal
    from sqlalchemy import update as _update
    updated = 0

    # ── Path A：signal_id 链路 ──
    path_a_rows = (await session.execute(
        select(
            TradingSignal.id.label("sig_id"),
            TradeJournal.entry_price,
            TradeJournal.exit_price,
            TradeJournal.realized_pnl,
            TradeJournal.quantity,
        )
        .join(
            TradeJournal,
            and_(
                TradingSignal.signal_id == TradeJournal.signal_id,
                TradeJournal.journal_status.in_(["CLOSED", "COMPLETED", "DONE"]),
                TradeJournal.exit_price.isnot(None),
                TradeJournal.entry_price.isnot(None),
                TradeJournal.entry_price != 0,
            ),
        )
        .where(TradingSignal.actual_return.is_(None))
        .limit(500)
    )).all()

    for row in path_a_rows:
        try:
            entry = float(row.entry_price)
            exit_ = float(row.exit_price)
            actual_return = (exit_ - entry) / entry if entry != 0 else None
            pnl_pct: Optional[float] = None
            if row.realized_pnl is not None and row.quantity is not None:
                qty = abs(float(row.quantity))
                if qty != 0 and entry != 0:
                    pnl_pct = float(row.realized_pnl) / (qty * entry)
            await session.execute(
                _update(TradingSignal)
                .where(TradingSignal.id == row.sig_id)
                .values(actual_return=actual_return, pnl_pct=pnl_pct)
            )
            updated += 1
        except Exception as exc:
            logger.debug("[DataSync] path_a skip: %s", exc)

    # ── Path B：旧 COMPLETED 日志无 signal_id，尝试按 account+symbol 匹配 ──
    # 取最近 90 天内未链接 signal 的已完成日志
    since = datetime.now(tz=timezone.utc) - timedelta(days=90)
    old_journals = (await session.execute(
        select(TradeJournal)
        .where(
            TradeJournal.signal_id.is_(None),
            TradeJournal.journal_status.in_(["CLOSED", "COMPLETED", "DONE"]),
            TradeJournal.exit_price.isnot(None),
            TradeJournal.entry_price.isnot(None),
            TradeJournal.created_at >= since,
        )
        .limit(200)
    )).scalars().all()

    for j in old_journals:
        # 找同 account×symbol×日期±7天内 actual_return 为空的信号
        _j_exit_date: Optional[date] = getattr(j, 'exit_date', None)
        _j_created_at: Optional[datetime] = getattr(j, 'created_at', None)
        j_date: Optional[date] = _j_exit_date or (_j_created_at.date() if _j_created_at is not None else None)
        if j_date is None:
            continue
        date_low = datetime.combine(j_date - timedelta(days=7), datetime.min.time()).replace(tzinfo=timezone.utc)
        date_high = datetime.combine(j_date + timedelta(days=7), datetime.max.time()).replace(tzinfo=timezone.utc)

        candidate = (await session.execute(
            select(TradingSignal.id)
            .where(
                TradingSignal.account_id == j.account_id,
                TradingSignal.symbol == j.symbol,
                TradingSignal.actual_return.is_(None),
                TradingSignal.created_at.between(date_low, date_high),
            )
            .order_by(TradingSignal.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()

        if candidate is None:
            continue

        entry = float(getattr(j, 'entry_price') or 0)
        exit_ = float(getattr(j, 'exit_price') or 0)
        if entry == 0:
            continue
        actual_return = (exit_ - entry) / entry
        _j_pnl = getattr(j, 'realized_pnl', None)
        _j_qty = getattr(j, 'quantity', None)
        pnl_pct = float(_j_pnl) / (abs(float(_j_qty or 1)) * entry) if _j_pnl is not None else None

        try:
            await session.execute(
                _update(TradingSignal)
                .where(TradingSignal.id == candidate)
                .values(actual_return=actual_return, pnl_pct=pnl_pct)
            )
            # 也把 signal_id 反链到 journal 防止重复匹配
            sig_uuid = (await session.execute(
                select(TradingSignal.signal_id).where(TradingSignal.id == candidate).limit(1)
            )).scalar_one_or_none()
            if sig_uuid:
                setattr(j, 'signal_id', sig_uuid)
            updated += 1
        except Exception as exc:
            logger.debug("[DataSync] path_b skip: %s", exc)

    if updated > 0:
        await session.commit()
    return updated


async def signal_return_backfill_extra_job() -> None:
    """Job ②: 每 6 小时 — 多路径补填 TradingSignal.actual_return。"""
    from app.models.db import SessionLocal
    try:
        async with SessionLocal() as session:
            updated = await _do_signal_return_backfill_extra(session)
        if updated > 0:
            logger.info("[DataSync] signal_return_backfill_extra: updated=%d", updated)
            # 主动触发 IC 重算
            if updated >= 5:
                await _trigger_ic_recompute_all()
    except Exception as exc:
        logger.error("[DataSync] signal_return_backfill_extra_job FAILED: %s", exc, exc_info=True)


async def _trigger_ic_recompute_all() -> None:
    """触发所有账户的 IC 重算（在新 actual_return 写入后调用）。"""
    from app.models.db import SessionLocal
    from sqlalchemy import text
    try:
        from app.services.signal_intelligence_service import SignalIntelligenceService
        svc = SignalIntelligenceService()
        async with SessionLocal() as session:
            rows = (await session.execute(
                text("SELECT DISTINCT account_id FROM trading_signals LIMIT 50")
            )).fetchall()
            for (acc_id,) in rows:
                try:
                    await svc.get_signal_intelligence(session, str(acc_id))
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("[DataSync] IC recompute failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Job ③ : attribution_daily_backfill_job
# ─────────────────────────────────────────────────────────────────────────────

async def attribution_daily_backfill_job() -> None:
    """Job ③: 每天 23:30 — 增量回填 TradeAttributionEntry，并触发 IC 重算。"""
    from app.models.db import SessionLocal
    from app.services.trade_attribution_engine import trade_attribution_engine
    try:
        async with SessionLocal() as session:
            result = await trade_attribution_engine.backfill_from_journal(
                session, days=None, limit=2000, dry_run=False
            )
        inserted = result.get("inserted", 0)
        logger.info(
            "[DataSync] attribution_daily_backfill: processed=%d inserted=%d skipped=%d",
            result.get("processed", 0), inserted, result.get("skipped_existing", 0),
        )
        if inserted >= 5:
            await _trigger_ic_recompute_all()
    except Exception as exc:
        logger.error("[DataSync] attribution_daily_backfill_job FAILED: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Job ④ : broker_order_sync_job
# ─────────────────────────────────────────────────────────────────────────────

async def broker_order_sync_job() -> None:
    """Job ④: 定时执行券商订单状态对账，并修复 stage7/stage8 残留计划。"""
    from app.models.db import SessionLocal
    from app.services.broker_order_sync_service import reconcile_broker_order_status
    from app.services.lifecycle_service import lifecycle_service

    try:
        async with SessionLocal() as session:
            result = await reconcile_broker_order_status(
                session,
                account_id=None,
                lookback_days=int(getattr(settings, "BROKER_ORDER_SYNC_LOOKBACK_DAYS", 3) or 3),
            )
            repaired_position_fsm = await lifecycle_service.sync_position_fsm_states(session)
            if repaired_position_fsm:
                await session.commit()

        logger.info(
            "[DataSync] broker_order_sync: synced_executing=%s updates=%s cancelled_synced=%s filled_synced=%s orphan_fixed=%s journal_created=%s repaired_position_fsm=%s",
            result.get("synced_executing", 0),
            result.get("synced_updates", 0),
            result.get("cancelled_synced", 0),
            result.get("filled_synced", 0),
            result.get("orphan_fixed", 0),
            result.get("journal_created", 0),
            repaired_position_fsm,
        )
    except Exception as exc:
        logger.error("[DataSync] broker_order_sync_job FAILED: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# 注册函数
# ─────────────────────────────────────────────────────────────────────────────

def register_data_sync_jobs(scheduler) -> None:
    """注册三个数据自动同步 Job 到 APScheduler。

    ① journal_auto_close:          每 30 分钟  — 出场信号 → 关闭 DRAFT 日志
    ② signal_return_backfill_extra: 每 6 小时  — 多路径补填 actual_return
    ③ attribution_daily_backfill:   每天 23:30 — 增量写入 TradeAttributionEntry
    ④ broker_order_sync:            每 N 分钟   — 券商订单状态对账，推进 stage7/stage8 计划
    """
    # ① 每 30 分钟关闭 DRAFT 日志
    scheduler.add_job(
        journal_auto_close_job,
        trigger="interval",
        minutes=30,
        id="journal_auto_close",
        name="[DataSync] Journal Auto-Close (exit signal → close DRAFT journal)",
        replace_existing=True,
    )

    # ② 每 6 小时补填 actual_return
    scheduler.add_job(
        signal_return_backfill_extra_job,
        trigger="interval",
        hours=6,
        id="signal_return_backfill_extra",
        name="[DataSync] Signal Return Backfill Extra (multi-path)",
        replace_existing=True,
    )

    # ③ 每天 23:30 归因回填
    scheduler.add_job(
        attribution_daily_backfill_job,
        trigger="cron",
        hour=23,
        minute=30,
        id="attribution_daily_backfill",
        name="[DataSync] Attribution Daily Backfill (trade_journal → attribution_entries)",
        replace_existing=True,
    )

    # ④ 每 N 分钟执行券商订单状态对账
    scheduler.add_job(
        broker_order_sync_job,
        trigger="interval",
        minutes=max(1, int(getattr(settings, 'BROKER_ORDER_SYNC_INTERVAL_MINUTES', 10) or 10)),
        id="broker_order_sync_job",
        name="[DataSync] Broker Order Sync (reconcile pipeline stage 7/8)",
        replace_existing=True,
        next_run_time=datetime.now() + timedelta(seconds=45),
    )

    logger.info("[DataSync] Data sync jobs registered:")
    logger.info("  ① journal_auto_close:           every 30m (exit signal closes DRAFT)")
    logger.info("  ② signal_return_backfill_extra:  every 6h  (actual_return multi-path)")
    logger.info("  ③ attribution_daily_backfill:    23:30 daily")
    logger.info("  ④ broker_order_sync:             every %sm (broker reconcile + lifecycle repair)", getattr(settings, 'BROKER_ORDER_SYNC_INTERVAL_MINUTES', 10))
