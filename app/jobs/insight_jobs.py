"""V10.2-M6: AI 洞察定时任务

任务：
  weekly_insight_run — 每周日 22:00 调用 WeeklyInsightGenerator，
                       分析过去 30 天交易数据，生成 AI 经验规则

注册方式::

    from app.jobs.insight_jobs import register_insight_jobs
    register_insight_jobs(scheduler)
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


async def _run_weekly_insight_generation() -> None:
    """每周日 22:00 触发洞察生成任务。"""
    try:
        # db module only exports SessionLocal; alias it for async use
        from app.models.db import SessionLocal as AsyncSessionLocal
        from app.services.insight_service import weekly_insight_generator

        async with AsyncSessionLocal() as db:
            created = await weekly_insight_generator.run(db)
            logger.info(f"[InsightJob] weekly run complete: {len(created)} insights generated")
    except Exception as e:
        logger.error(f"[InsightJob] weekly_insight_run failed: {e}", exc_info=True)


async def _run_ab_experiment_checker() -> None:
    """每天 08:00 检查到期的 A/B 实验并执行统计显著性检验。"""
    try:
        from datetime import datetime, timezone

        from app.models.ai_insight import ABExperiment, ExperimentStatus
        # db module only exports SessionLocal; alias it for async use
        from app.models.db import SessionLocal as AsyncSessionLocal
        from app.services.insight_service import ab_test_engine
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            now = datetime.now(tz=timezone.utc)
            stmt = (
                select(ABExperiment)
                .where(ABExperiment.status == ExperimentStatus.RUNNING)
            )
            experiments = list((await db.execute(stmt)).scalars().all())

            for exp in experiments:
                # 检查是否到期
                from datetime import timedelta
                end_dt = exp.start_date + timedelta(days=exp.duration_days)
                if now < end_dt:
                    continue

                # 此处简化：从实际 paper trade 结果中获取数据
                # 生产中应查询 paper_trading_orders 表
                logger.info(f"[InsightJob] experiment {exp.id} '{exp.experiment_name}' ready for evaluation")
                # 占位：实际评估需要真实 paper trade PnL 数据
    except Exception as e:
        logger.error(f"[InsightJob] ab_experiment_checker failed: {e}", exc_info=True)


def register_insight_jobs(scheduler: AsyncIOScheduler) -> None:
    """注册洞察相关定时任务。"""
    # 每周日 22:00 生成洞察
    scheduler.add_job(
        _run_weekly_insight_generation,
        trigger=CronTrigger(day_of_week="sun", hour=22, minute=0, timezone="America/New_York"),
        id="weekly_insight_run",
        name="Weekly AI Insight Generation (Sun 22:00 ET)",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    # 每天 08:00 检查 A/B 实验到期
    scheduler.add_job(
        _run_ab_experiment_checker,
        trigger=CronTrigger(hour=8, minute=0, timezone="America/New_York"),
        id="ab_experiment_checker",
        name="Daily A/B Experiment Expiry Check (08:00 ET)",
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("[InsightJob] registered: weekly_insight_run + ab_experiment_checker")
