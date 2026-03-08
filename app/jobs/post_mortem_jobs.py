"""V10.5.2: 决策事后剖析自动化任务

触发机制：
  1. EventBus 钩子（实时）：仓位完全平仓（Topics.POSITION_CLOSED）时立即排队
  2. 每日兜底 Cron（02:00 UTC）：扫描最近 90 天内已平仓但缺失剖析的仓位

注册方式（在 main.py lifespan 中调用）::

    from app.jobs.post_mortem_jobs import register_post_mortem_jobs
    register_post_mortem_jobs(scheduler)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# 模块级集合：持有运行中的后台任务引用，防止 GC 提前回收
_RUNNING_TASKS: set[asyncio.Task] = set()

_POST_MORTEM_SCAN_DAYS = 90  # 兜底 cron 扫描窗口（天）
_POST_MORTEM_BATCH_LIMIT = 20  # 每次兜底 cron 最多处理条数（避免深夜 API 风暴）


# 内部辅助


def _direction_from_position(pos) -> str:
    d = (getattr(pos, "direction", "") or "").strip().upper()
    if d in {"SHORT", "SELL", "S"}:
        return "SELL"
    return "BUY"


def _hold_days_from_position(pos) -> int:
    opened_at = getattr(pos, "opened_at", None)
    closed_at = getattr(pos, "closed_at", None)
    if opened_at and closed_at:
        delta = closed_at.replace(tzinfo=None) - opened_at.replace(tzinfo=None)
        return max(1, delta.days)
    return 1


async def _enqueue_for_position(pos, account_id: str) -> None:
    """为单个 Position 创建 post-mortem 记录并后台排队生成。"""
    try:
        from app.models.db import get_session_ctx
        from app.services.decision_post_mortem_service import (
            decision_post_mortem_service,
        )

        trade_id = f"position-{pos.id}"
        entry_price = float(getattr(pos, "avg_entry_price", None) or 0.0)
        exit_price = float(getattr(pos, "avg_close_price", None) or 0.0)
        realized_pnl = float(getattr(pos, "realized_pnl", None) or 0.0)
        direction = _direction_from_position(pos)
        hold_days = _hold_days_from_position(pos)

        if entry_price <= 0 or exit_price <= 0:
            logger.debug(
                "[PostMortemJob] Skipping position %s: missing price data", pos.id
            )
            return

        async with get_session_ctx() as db:
            pm, should_queue = await decision_post_mortem_service.request_post_mortem(
                db=db,
                account_id=account_id,
                trade_id=trade_id,
                symbol=pos.symbol,
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                hold_days=hold_days,
            )
            await db.commit()

        if not should_queue:
            logger.debug(
                "[PostMortemJob] PostMortem already queued/done for trade_id=%s",
                trade_id,
            )
            return

        # fire-and-forget 后台生成（独立 session，不阻塞调用方）
        # 存入模块级集合防止 GC 提前回收
        _task = asyncio.create_task(
            decision_post_mortem_service.enqueue_post_mortem_generation(
                pm_id=pm.id,
                account_id=account_id,
                symbol=pos.symbol,
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                hold_days=hold_days,
                trade_context={
                    "source": "auto",
                    "closing_reason": getattr(pos, "closing_reason", ""),
                },
            ),
            name=f"post-mortem-{pm.id}",
        )
        _RUNNING_TASKS.add(_task)
        _task.add_done_callback(_RUNNING_TASKS.discard)
        logger.info(
            "[PostMortemJob] Queued post-mortem for %s (position_id=%s, trade_id=%s)",
            pos.symbol,
            pos.id,
            trade_id,
        )
    except Exception as exc:
        logger.warning(
            "[PostMortemJob] Failed to enqueue for position %s: %s",
            getattr(pos, "id", "?"),
            exc,
        )


# EventBus 钩子（实时触发）


async def on_position_closed(payload: dict) -> None:
    """POSITION_CLOSED 事件处理器：仓位平仓后立即排队 AI 剖析。

    payload: {"position_id": int, "symbol": str, "closing_reason": str, "realized_pnl": float}
    """
    position_id = payload.get("position_id")
    if not position_id:
        return

    try:
        from sqlalchemy import select

        from app.models.db import get_session_ctx
        from app.models.position import Position

        async with get_session_ctx() as db:
            pos = (
                await db.execute(select(Position).where(Position.id == position_id))
            ).scalar_one_or_none()
            if pos is None:
                logger.warning(
                    "[PostMortemJob] Position %s not found in DB", position_id
                )
                return
            account_id = pos.account_id or ""

        await _enqueue_for_position(pos, account_id)

    except Exception as exc:
        logger.warning("[PostMortemJob] on_position_closed error: %s", exc)


# 兜底 Cron：每日 02:00 UTC 扫描遗漏的已平仓仓位


async def _run_post_mortem_scan() -> None:
    """扫描最近 N 天内已平仓但缺少 post-mortem 的仓位，逐个排队。"""
    try:
        from sqlalchemy import select

        from app.models.db import get_session_ctx
        from app.models.decision_post_mortem import DecisionPostMortem
        from app.models.position import Position, PositionStatus

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=_POST_MORTEM_SCAN_DAYS
        )

        async with get_session_ctx() as db:
            # 已有 post-mortem 且非失败状态的 trade_id
            existing_stmt = select(DecisionPostMortem.trade_id).where(
                DecisionPostMortem.status.notin_(["failed"])
            )
            existing_trade_ids: set[str] = set(
                (await db.execute(existing_stmt)).scalars().all()
            )

            # 查近期平仓仓位
            closed_stmt = (
                select(Position)
                .where(
                    Position.status.in_(
                        [PositionStatus.CLOSED.value, PositionStatus.LIQUIDATED.value]
                    ),
                    Position.closed_at >= cutoff,
                    Position.avg_entry_price.isnot(None),
                    Position.avg_close_price.isnot(None),
                )
                .order_by(Position.closed_at.desc())
                .limit(_POST_MORTEM_BATCH_LIMIT * 5)
            )
            positions = (await db.execute(closed_stmt)).scalars().all()

        # 过滤掉已有 post-mortem 的
        pending = [
            p for p in positions if f"position-{p.id}" not in existing_trade_ids
        ][:_POST_MORTEM_BATCH_LIMIT]

        if not pending:
            logger.info("[PostMortemJob] Cron scan: no missing post-mortems found")
            return

        logger.info(
            "[PostMortemJob] Cron scan: %d positions missing post-mortem, enqueueing...",
            len(pending),
        )
        for pos in pending:
            await _enqueue_for_position(pos, pos.account_id or "")
            # 轻微间隔，避免 IO 爆发
            await asyncio.sleep(0.5)

    except Exception as exc:
        logger.error("[PostMortemJob] Cron scan failed: %s", exc, exc_info=True)


def register_post_mortem_jobs(scheduler: AsyncIOScheduler) -> None:
    """注册事后剖析相关任务：EventBus 订阅 + 每日兜底 Cron。"""
    from app.core.event_bus import Topics, event_bus

    # 1. 实时：订阅平仓事件
    event_bus.subscribe(Topics.POSITION_CLOSED, on_position_closed)
    logger.info("[PostMortemJob] Subscribed to POSITION_CLOSED event")

    # 2. 兜底：每日 02:00 UTC 扫描
    scheduler.add_job(
        _run_post_mortem_scan,
        trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="post_mortem_daily_scan",
        name="[V10.5.2] PostMortem Daily Catch-up Scan (02:00 UTC)",
        replace_existing=True,
    )
    logger.info("[PostMortemJob] Registered daily post-mortem scan @ 02:00 UTC")
