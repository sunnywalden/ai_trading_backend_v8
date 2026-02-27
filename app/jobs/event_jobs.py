"""V10.2-M2: 事件日历定时任务

任务：
  event_calendar_scan — 每日 07:00 扫描持仓中的股票，更新事件日历并触发围栏检查

注册方式（在 main.py lifespan 中调用）::

    from app.jobs.event_jobs import register_event_jobs
    register_event_jobs(scheduler)
"""
from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


async def _run_event_calendar_scan() -> None:
    """每日 07:00 触发事件日历扫描任务。"""
    try:
        # db.py defines SessionLocal (AsyncSession) – alias for clarity
        from app.models.db import SessionLocal as AsyncSessionLocal
        from app.services.event_calendar_service import event_calendar_service

        # 假设持仓股票列表从数据库读取（此处演示：读取 positions 表中的唯一 symbol）
        async with AsyncSessionLocal() as db:
            symbols = await _get_held_symbols(db)
            if not symbols:
                logger.info("[EventJob] no held positions, skipping calendar scan")
                return
            added = await event_calendar_service.scan_and_upsert(db, symbols=symbols, lookahead_days=5)
            logger.info(f"[EventJob] scan complete: {len(added)} new entries for {len(symbols)} symbols")
    except Exception as e:
        logger.error(f"[EventJob] event_calendar_scan failed: {e}", exc_info=True)


async def _get_held_symbols(db: Any) -> list[str]:
    """从持仓表读取当前持有的唯一 symbol 列表。"""
    try:
        from sqlalchemy import text

        result = await db.execute(text("SELECT DISTINCT symbol FROM positions WHERE status = 'open' LIMIT 100"))
        return [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.warning(f"[EventJob] get_held_symbols failed: {e}")
        return []


def register_event_jobs(scheduler: AsyncIOScheduler) -> None:
    """
    注册所有事件相关定时任务到 APScheduler。

    调用时机：应在 FastAPI lifespan startup 阶段调用。
    """
    scheduler.add_job(
        _run_event_calendar_scan,
        trigger=CronTrigger(hour=7, minute=0, timezone="America/New_York"),
        id="event_calendar_scan",
        name="Daily Event Calendar Scan (07:00 ET)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("[EventJob] registered: event_calendar_scan @ 07:00 ET daily")
