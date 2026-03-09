"""
定时数据刷新任务

8个定时任务:
1. 技术指标刷新 - 每1小时
2. 基本面数据刷新 - 每天凌晨2点
3. 宏观指标刷新 - 每天早上9点
4. 地缘政治事件抓取 - 每4小时
5. 宏观风险计算 - 每6小时
6. 旧数据清理 - 每天凌晨3点
7. 交易计划过期标记 - 每天00:30
8. 全量美/港股标的同步 - 每周一次
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.symbol_behavior_stats import SymbolBehaviorStats
from app.models.symbol_risk_profile import SymbolRiskProfile
from app.models.trading_plan import TradingPlan
from app.services.geopolitical_events_service import GeopoliticalEventsService
from app.services.macro_indicators_service import MacroIndicatorsService
from app.services.macro_risk_scoring_service import MacroRiskScoringService
from app.services.market_universe_service import MarketUniverseService

logger = logging.getLogger(__name__)


# 延迟导入get_session避免循环依赖
def _get_session():
    from app.models.db import SessionLocal

    return SessionLocal()


async def refresh_technical_indicators_job():
    """任务1: 刷新技术指标数据

    频率: 每1小时
    功能: 更新所有活跃持仓的技术指标缓存
    """
    try:
        logger.info("Starting technical indicators refresh job")
        start_time = datetime.now()

        from app.services.quote_freshness_service import \
            refresh_quote_freshness

        async with _get_session() as session:
            refresh_result = await refresh_quote_freshness(
                session,
                account_id=settings.TIGER_ACCOUNT,
                max_symbols=max(4, settings.REFRESH_CONCURRENCY),
            )

        success_count = int(refresh_result.get("success_count", 0))
        error_count = int(refresh_result.get("failure_count", 0))
        symbols = refresh_result.get("symbols_attempted", [])
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Technical indicators refresh completed: "
            f"{success_count} success, {error_count} errors, "
            f"symbols={symbols}, took {elapsed:.2f}s"
        )

    except Exception as e:
        logger.error(
            f"Technical indicators refresh job failed: {str(e)}", exc_info=True
        )


async def refresh_fundamental_data_job():
    """任务2: 刷新基本面数据

    频率: 每天凌晨2点
    功能: 更新所有活跃持仓的基本面财务数据
    """
    try:
        logger.info("Starting fundamental data refresh job")
        start_time = datetime.now()

        # 获取所有需要刷新的symbol
        trade_client = make_option_broker_client()
        account_id = await trade_client.get_account_id()
        positions = await trade_client.list_underlying_positions(account_id)

        if not positions:
            logger.info("No positions found, skipping fundamental refresh")
            return

        symbols = [pos.symbol for pos in positions]
        success_count = 0
        error_count = 0

        # 调用FundamentalAnalysisService刷新基本面数据
        from app.services.fundamental_analysis_service import \
            FundamentalAnalysisService

        fundamental_service = FundamentalAnalysisService()

        for symbol in symbols:
            try:
                await fundamental_service.get_fundamental_data(
                    symbol, force_refresh=True
                )
                success_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to refresh fundamental data for {symbol}: {str(e)}"
                )
                error_count += 1

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Fundamental data refresh completed: "
            f"{success_count} success, {error_count} errors, "
            f"took {elapsed:.2f}s"
        )

    except Exception as e:
        logger.error(f"Fundamental data refresh job failed: {str(e)}", exc_info=True)


async def refresh_macro_indicators_job():
    """任务3: 刷新宏观指标数据

    频率: 每天早上9点
    功能: 从FRED API获取最新的宏观经济指标
    """
    try:
        logger.info("Starting macro indicators refresh job")
        start_time = datetime.now()

        macro_service = MacroIndicatorsService()
        results = await macro_service.refresh_all_indicators()

        success_count = results.get("success_count", 0)
        error_count = results.get("error_count", 0)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Macro indicators refresh completed: "
            f"{success_count} success, {error_count} errors, "
            f"took {elapsed:.2f}s"
        )

    except Exception as e:
        logger.error(f"Macro indicators refresh job failed: {str(e)}", exc_info=True)


async def fetch_geopolitical_events_job():
    """任务4: 抓取地缘政治事件

    频率: 每4小时
    功能: 从News API获取最新的地缘政治事件
    """
    try:
        logger.info("Starting geopolitical events fetch job")
        start_time = datetime.now()

        geo_service = GeopoliticalEventsService()
        events = await geo_service.fetch_recent_events(days=7, force_refresh=True)

        event_count = len(events)
        elapsed = (datetime.now() - start_time).total_seconds()

        logger.info(
            f"Geopolitical events fetch completed: "
            f"{event_count} events fetched, "
            f"took {elapsed:.2f}s"
        )

    except Exception as e:
        logger.error(f"Geopolitical events fetch job failed: {str(e)}", exc_info=True)


async def calculate_macro_risk_job():
    """任务5: 计算宏观风险评分

    频率: 每6小时
    功能: 基于最新数据计算5维度宏观风险评分
    """
    try:
        logger.info("Starting macro risk calculation job")
        start_time = datetime.now()

        risk_service = MacroRiskScoringService()
        risk_score = await risk_service.calculate_macro_risk_score(use_cache=False)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Macro risk calculation completed: "
            f"overall_score={risk_score.overall_score:.2f}, "
            f"risk_level={risk_score.risk_level}, "
            f"took {elapsed:.2f}s"
        )

    except Exception as e:
        logger.error(f"Macro risk calculation job failed: {str(e)}", exc_info=True)


async def cleanup_old_data_job():
    """任务6: 清理旧数据

    频率: 每天凌晨3点
    功能: 删除超过保留期限的历史数据
    """
    try:
        logger.info("Starting old data cleanup job")
        start_time = datetime.now()

        # 保留期限（天）
        BEHAVIOR_STATS_RETENTION_DAYS = 90  # 行为统计保留90天
        RISK_PROFILE_RETENTION_DAYS = 90  # 风险档案保留90天
        GEO_EVENTS_RETENTION_DAYS = 60  # 地缘事件保留60天
        MACRO_INDICATORS_RETENTION_DAYS = 365  # 宏观指标保留1年

        cutoff_behavior = datetime.now() - timedelta(days=BEHAVIOR_STATS_RETENTION_DAYS)
        cutoff_risk = datetime.now() - timedelta(days=RISK_PROFILE_RETENTION_DAYS)
        cutoff_geo = datetime.now() - timedelta(days=GEO_EVENTS_RETENTION_DAYS)
        cutoff_macro = datetime.now() - timedelta(days=MACRO_INDICATORS_RETENTION_DAYS)

        deleted_counts = {
            "behavior_stats": 0,
            "risk_profiles": 0,
            "geo_events": 0,
            "macro_indicators": 0,
        }

        async with _get_session() as session:
            try:
                # 清理行为统计数据
                result = await session.execute(
                    delete(SymbolBehaviorStats).where(
                        SymbolBehaviorStats.updated_at < cutoff_behavior
                    )
                )
                deleted_counts["behavior_stats"] = result.rowcount  # type: ignore[attr-defined]

                # 清理风险档案数据
                result = await session.execute(
                    delete(SymbolRiskProfile).where(
                        SymbolRiskProfile.updated_at < cutoff_risk
                    )
                )
                deleted_counts["risk_profiles"] = result.rowcount  # type: ignore[attr-defined]

                # 清理地缘政治事件（需要先添加对应的model）
                # 由于GeopoliticalEvent model在service中定义，这里暂时跳过
                # 实际应该将model定义移到models目录

                # 清理宏观指标数据（如果有单独的表存储）
                # 同样需要model定义

                await session.commit()

                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(
                    f"Old data cleanup completed: "
                    f"behavior_stats={deleted_counts['behavior_stats']}, "
                    f"risk_profiles={deleted_counts['risk_profiles']}, "
                    f"took {elapsed:.2f}s"
                )

            except Exception as e:
                await session.rollback()
                logger.error(f"Database cleanup failed: {str(e)}")
                raise

    except Exception as e:
        logger.error(f"Old data cleanup job failed: {str(e)}", exc_info=True)


async def plan_expiration_job():
    """任务8: 交易计划过期标记

    频率: 每天凌晨 0:30
    功能: 将已过期的 ACTIVE 计划标记为 EXPIRED
    """
    try:
        logger.info("Starting plan expiration job")
        start_time = datetime.now()

        async with _get_session() as session:
            try:
                result = await session.execute(
                    select(TradingPlan).where(
                        TradingPlan.plan_status == "ACTIVE",
                        TradingPlan.valid_until.is_not(None),
                        TradingPlan.valid_until < datetime.now(),
                    )
                )
                plans = list(result.scalars().all())
                if plans:
                    now_utc = datetime.now(timezone.utc)
                    for plan in plans:
                        old_stage = plan.pipeline_stage
                        plan.plan_status = "EXPIRED"
                        plan.pipeline_stage = 16  # 已归档
                        plan.stage_entered_at = now_utc
                        session.add(
                            FsmTransitionLog(
                                plan_id=plan.id,
                                fsm_type="PLAN",
                                from_state=(
                                    f"STAGE_{old_stage}"
                                    if old_stage is not None
                                    else "UNKNOWN"
                                ),
                                to_state="STAGE_16",
                                trigger_reason="计划到期自动归档 (plan_expiration_job)",
                            )
                        )
                    await session.commit()
                expired_count = len(plans)
            except Exception:
                await session.rollback()
                raise

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Plan expiration completed: expired={expired_count}, took {elapsed:.2f}s"
        )
    except Exception as e:
        logger.error(f"Plan expiration job failed: {str(e)}", exc_info=True)


async def refresh_market_universe_weekly_job():
    """任务8: 每周全量同步美股/港股股票池到本地。

    频率: 每周一次
    功能: 从 Tiger API 拉取 US/HK 全量股票代码，落库并写入缓存
    """
    try:
        logger.info("Starting weekly market-universe refresh job")
        start_time = datetime.now()

        async with _get_session() as session:
            svc = MarketUniverseService(session)
            result = await svc.refresh_all_markets()

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Weekly market-universe refresh completed: US=%s, HK=%s, took %.2fs",
            result.get("US"),
            result.get("HK"),
            elapsed,
        )
    except Exception as e:
        logger.error(
            f"Weekly market-universe refresh job failed: {str(e)}", exc_info=True
        )


def register_all_jobs(scheduler):
    """注册所有定时任务到调度器

    Args:
        scheduler: APScheduler实例
    """
    from app.jobs.scheduler import add_job

    # 任务1: 技术指标刷新 - 每1小时
    add_job(
        func=refresh_technical_indicators_job,
        trigger="interval",
        id="refresh_technical_indicators",
        name="刷新技术指标",
        hours=1,
        next_run_time=datetime.now() + timedelta(minutes=5),  # 5分钟后首次运行
    )

    # 任务2: 基本面数据刷新 - 每天凌晨2点
    add_job(
        func=refresh_fundamental_data_job,
        trigger="cron",
        id="refresh_fundamental_data",
        name="刷新基本面数据",
        hour=2,
        minute=0,
    )

    # 任务3: 宏观指标刷新 - 每天早上9点
    add_job(
        func=refresh_macro_indicators_job,
        trigger="cron",
        id="refresh_macro_indicators",
        name="刷新宏观指标",
        hour=9,
        minute=0,
    )

    # 任务4: 地缘政治事件抓取 - 每4小时
    add_job(
        func=fetch_geopolitical_events_job,
        trigger="interval",
        id="fetch_geopolitical_events",
        name="抓取地缘政治事件",
        hours=4,
        next_run_time=datetime.now() + timedelta(minutes=10),  # 10分钟后首次运行
    )

    # 任务5: 宏观风险计算 - 每6小时
    add_job(
        func=calculate_macro_risk_job,
        trigger="interval",
        id="calculate_macro_risk",
        name="计算宏观风险",
        hours=6,
        next_run_time=datetime.now() + timedelta(minutes=15),  # 15分钟后首次运行
    )

    # 任务6: 旧数据清理 - 每天凌晨3点
    add_job(
        func=cleanup_old_data_job,
        trigger="cron",
        id="cleanup_old_data",
        name="清理旧数据",
        hour=3,
        minute=0,
    )

    # 任务7: 交易计划过期标记 - 每天北京时间00:30
    add_job(
        func=plan_expiration_job,
        trigger="cron",
        id="plan_expiration_job",
        name="交易计划过期标记(00:30)",
        hour=0,
        minute=30,
    )

    # 任务8: 全量美/港股标的同步 - 每周日 06:00
    add_job(
        func=refresh_market_universe_weekly_job,
        trigger="cron",
        id="refresh_market_universe_weekly",
        name="每周同步美港股全量标的",
        day_of_week="sun",
        hour=6,
        minute=0,
    )

    logger.info("All scheduled jobs registered successfully")
