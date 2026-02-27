"""V10.2-M1: 市场体制分类定时任务

每日 08:00 UTC 运行 RegimeClassifier，结果持久化到 DB，
并通过 EventBus 广播 REGIME_CHANGED（如体制切换）。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

logger = logging.getLogger(__name__)


async def run_regime_classification(force: bool = False) -> None:
    """
    运行体制分类。
    :param force: 是否强制执行(忽略缓存或其他限制)
    """
    logger.info(f"[RegimeJob] Starting market regime classification (force={force})...")
    try:
        from app.models.db import SessionLocal
        from app.services.regime_classifier import regime_classifier

        async with SessionLocal() as db:
            # 如果不是强制运行且已存在今日数据，可以跳过(此处 run 内部已有业务幂等)
            result = await regime_classifier.run(db)
            logger.info(
                f"[RegimeJob] Classification complete: "
                f"candidate={result.get('candidate')}, "
                f"confirmed={result.get('confirmed')}, "
                f"confidence={result.get('confidence', 0):.2%}"
            )
    except Exception as exc:
        logger.error(f"[RegimeJob] Regime classification failed: {exc}", exc_info=True)


def register_regime_jobs(scheduler: "AsyncIOScheduler") -> None:
    """
    注册体制感知定时任务到 APScheduler。
    在 app/main.py lifespan 中调用。
    """
    if not settings.REGIME_ENABLED:
        logger.info("[RegimeJob] REGIME_ENABLED=False, skipping job registration")
        return

    # 1. 每日定时运行
    scheduler.add_job(
        run_regime_classification,
        "cron",
        hour=settings.REGIME_CLASSIFICATION_HOUR,
        minute=0,
        id="regime_daily_classification",
        replace_existing=True,
    )
    logger.info(f"[RegimeJob] Registered daily job at {settings.REGIME_CLASSIFICATION_HOUR}:00 UTC")
    return

    hour = settings.REGIME_CLASSIFICATION_HOUR

    scheduler.add_job(
        run_daily_regime_classification,
        trigger="cron",
        hour=hour,
        minute=0,
        second=0,
        id="daily_regime_classification",
        name="每日市场体制分类 (V10.2-M1)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,  # 若上次未完成则跳过重复触发
        misfire_grace_time=3600,  # 允许 1 小时内补发
    )

    logger.info(
        f"[RegimeJob] Registered 'daily_regime_classification' "
        f"— runs daily at {hour:02d}:00 UTC"
    )
