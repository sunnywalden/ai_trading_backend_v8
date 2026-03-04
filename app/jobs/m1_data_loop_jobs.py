"""
V10.4 M1 数据循环任务

T1.1 ReturnBackfillJob: 每日收盘后将已关闭 journal 的实际收益率回填到 trading_signals.actual_return
T1.3 IC 计算触发: 回填数量 >= 10 条时触发 signal_intelligence_service 重算全量用户 IC
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import TradingSignal
from app.models.trade_journal import TradeJournal

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────
BACKFILL_BATCH_SIZE = 500       # 单次回填上限，防止事务过大
IC_RECOMPUTE_THRESHOLD = 10     # 至少回填多少条才触发 IC 重算


# ─────────────────────────────────────────────
# ReturnBackfillJob
# ─────────────────────────────────────────────
async def _do_return_backfill(session: AsyncSession) -> int:
    """
    核心回填逻辑：
      1. 找出 actual_return IS NULL 且对应 journal 已关闭（有 exit_price）的信号
      2. 计算 actual_return = (exit_price - entry_price) / entry_price
         pnl_pct         = realized_pnl / (|qty| * entry_price)   （若字段存在）
      3. 批量写回 trading_signals
    返回本次更新条数。
    """
    # ── 查询：trading_signals JOIN trade_journal ──
    stmt = (
        select(
            TradingSignal.id,
            TradingSignal.signal_id,
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
        .limit(BACKFILL_BATCH_SIZE)
    )

    rows = (await session.execute(stmt)).all()
    if not rows:
        return 0

    updated = 0
    for row in rows:
        try:
            actual_return: Optional[float] = None
            pnl_pct: Optional[float] = None

            entry_price = float(row.entry_price)
            exit_price = float(row.exit_price)

            if entry_price != 0:
                actual_return = (exit_price - entry_price) / entry_price

            if row.realized_pnl is not None and row.quantity is not None:
                qty = abs(float(row.quantity))
                if qty != 0 and entry_price != 0:
                    pnl_pct = float(row.realized_pnl) / (qty * entry_price)

            await session.execute(
                update(TradingSignal)
                .where(TradingSignal.id == row.id)
                .values(
                    actual_return=actual_return,
                    pnl_pct=pnl_pct,
                )
            )
            updated += 1
        except Exception as exc:
            logger.warning(f"[ReturnBackfill] 跳过 signal_id={row.signal_id}: {exc}")

    await session.commit()
    return updated


async def return_backfill_job() -> None:
    """
    ReturnBackfillJob —— 每日 21:30 ET（美股收盘约 1.5h 后）执行
    将已关闭的 TradeJournal 实际收益率回填至对应 TradingSignal.actual_return
    若本次回填 >= IC_RECOMPUTE_THRESHOLD 条，额外触发 IC 重算
    """
    from app.models.db import SessionLocal  # 延迟导入避免循环

    start_ts = datetime.now(tz=timezone.utc)
    logger.info("[ReturnBackfill] 任务开始")

    try:
        async with SessionLocal() as session:
            updated_count = await _do_return_backfill(session)

        logger.info(f"[ReturnBackfill] 完成，本次回填 {updated_count} 条")

        # ── T1.3: 触发 IC 重算 ──
        if updated_count >= IC_RECOMPUTE_THRESHOLD:
            await _trigger_ic_recompute()

        elapsed = (datetime.now(tz=timezone.utc) - start_ts).total_seconds()
        logger.info(f"[ReturnBackfill] 耗时 {elapsed:.1f}s")

    except Exception as exc:
        logger.error(f"[ReturnBackfill] 任务异常: {exc}", exc_info=True)


async def _trigger_ic_recompute() -> None:
    """触发 signal_intelligence_service 对所有用户重算 IC（T1.2）"""
    try:
        from app.services.signal_intelligence_service import SignalIntelligenceService
        from app.models.db import SessionLocal

        svc = SignalIntelligenceService()
        async with SessionLocal() as session:
            # 获取所有有信号记录的 account_id 列表
            result = await session.execute(
                text("SELECT DISTINCT account_id FROM trading_signals LIMIT 200")
            )
            account_ids = [row[0] for row in result.fetchall()]

        logger.info(f"[ReturnBackfill→IC] 触发 {len(account_ids)} 个账户的 IC 重算")
        async with SessionLocal() as session:
            for account_id in account_ids:
                try:
                    await svc.get_signal_intelligence(session, account_id)
                except Exception as exc:
                    logger.warning(f"[ReturnBackfill→IC] 账户 {account_id} IC 重算失败: {exc}")

    except Exception as exc:
        logger.error(f"[ReturnBackfill→IC] 触发 IC 重算异常: {exc}", exc_info=True)


# ─────────────────────────────────────────────
# 注册函数
# ─────────────────────────────────────────────
def register_m1_jobs(scheduler) -> None:  # noqa: ANN001
    """
    注册 V10.4 M1 定时任务

    - m1_return_backfill: 每日 21:30 ET（= 次日 02:30 UTC），
      将已关闭 journal 的实际收益率回填到 trading_signals
    """
    from app.jobs.scheduler import add_job

    add_job(
        func=return_backfill_job,
        trigger="cron",
        id="m1_return_backfill",
        name="[V10.4 M1] actual_return 回填",
        hour=2,
        minute=30,
        timezone="UTC",       # 21:30 ET ≈ 02:30 UTC（冬令时），夏令时用 01:30
    )
    logger.info("[M1 Jobs] ReturnBackfillJob 已注册 (02:30 UTC)")
