"""ai_hub_jobs.py — V10.3.3 AI 中枢定时任务

- 每日 08:15 ET：置信度校准（confidence_calibration_service）
- 每日 17:00 ET（市收后）：Kalman 因子权重更新（adaptive_factor_weighting_service）
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_confidence_calibration() -> None:
    """每日 08:15 运行置信度校准。"""
    from app.models.db import SessionLocal
    from app.services.confidence_calibration_service import confidence_calibration_service
    try:
        async with SessionLocal() as db:
            async with db.begin():
                # 对所有活跃用户运行校准
                from sqlalchemy import select, distinct
                from app.models.trading_signal import TradingSignal
                stmt = select(distinct(TradingSignal.user_id)).limit(100)
                rows = (await db.execute(stmt)).scalars().all()
                for user_id in rows:
                    try:
                        snap = await confidence_calibration_service.run_daily_calibration(db, user_id)
                        logger.info("Calibration done: user=%s ece=%.4f", user_id, snap.ece or 0)
                    except Exception as e:
                        logger.warning("Calibration failed for user=%s: %s", user_id, e)
    except Exception as e:
        logger.error("run_confidence_calibration failed: %s", e)


async def run_adaptive_weight_update() -> None:
    """每日收盘后运行 Kalman 权重更新。"""
    from app.models.db import SessionLocal
    from app.services.adaptive_factor_weighting_service import adaptive_factor_weighting_service
    try:
        async with SessionLocal() as db:
            async with db.begin():
                from sqlalchemy import select, distinct
                from app.models.trading_signal import TradingSignal
                stmt = select(distinct(TradingSignal.user_id)).limit(100)
                rows = (await db.execute(stmt)).scalars().all()
                for user_id in rows:
                    try:
                        recs = await adaptive_factor_weighting_service.run_daily_update(db, user_id)
                        logger.info("WeightUpdate done: user=%s records=%d", user_id, len(recs))
                    except Exception as e:
                        logger.warning("WeightUpdate failed for user=%s: %s", user_id, e)
    except Exception as e:
        logger.error("run_adaptive_weight_update failed: %s", e)


def register_ai_hub_jobs(scheduler) -> None:
    """注册 AI 中枢定时任务。"""
    # 置信度校准：每日 08:15
    scheduler.add_job(
        run_confidence_calibration,
        trigger="cron",
        hour=8,
        minute=15,
        id="ai_hub_confidence_calibration",
        replace_existing=True,
        name="[V10.3.3] 置信度校准（08:15 每日）",
    )
    # Kalman 权重更新：每日 17:00（美股收盘后 30min）
    scheduler.add_job(
        run_adaptive_weight_update,
        trigger="cron",
        hour=17,
        minute=0,
        id="ai_hub_kalman_weight_update",
        replace_existing=True,
        name="[V10.3.3] Kalman 因子权重更新（17:00 每日）",
    )
    logger.info("[V10.3.3] AI Hub jobs registered")
