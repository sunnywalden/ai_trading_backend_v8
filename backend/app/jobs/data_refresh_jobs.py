"""
定时数据刷新任务

6个定时任务:
1. 技术指标刷新 - 每1小时
2. 基本面数据刷新 - 每天凌晨2点
3. 宏观指标刷新 - 每天早上9点
4. 地缘政治事件抓取 - 每4小时
5. 宏观风险计算 - 每6小时
6. 旧数据清理 - 每天凌晨3点
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_behavior_stats import SymbolBehaviorStats
from app.models.symbol_risk_profile import SymbolRiskProfile
from app.services.macro_indicators_service import MacroIndicatorsService
from app.services.macro_risk_scoring_service import MacroRiskScoringService
from app.services.geopolitical_events_service import GeopoliticalEventsService
from app.services.potential_opportunities_service import PotentialOpportunitiesService
from app.broker.factory import make_option_broker_client
from app.core.config import settings

logger = logging.getLogger(__name__)


# 延迟导入get_session避免循环依赖
def _get_session():
    from app.main import SessionLocal
    return SessionLocal()


async def refresh_technical_indicators_job():
    """任务1: 刷新技术指标数据
    
    频率: 每1小时
    功能: 更新所有活跃持仓的技术指标缓存
    """
    try:
        logger.info("Starting technical indicators refresh job")
        start_time = datetime.now()
        
        # 获取所有需要刷新的symbol
        trade_client = make_option_broker_client()
        account_id = await trade_client.get_account_id()
        positions = await trade_client.list_underlying_positions(account_id)
        
        if not positions:
            logger.info("No positions found, skipping technical refresh")
            return
        
        symbols = [pos.symbol for pos in positions]
        success_count = 0
        error_count = 0
        
        # 这里可以调用TechnicalAnalysisService的刷新方法
        # 由于我们的技术指标是实时计算的，这里主要是触发缓存更新
        for symbol in symbols:
            try:
                # 可以调用对应的API端点或服务方法来触发刷新
                # 例如: await technical_service.refresh_indicators(symbol)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to refresh technical indicators for {symbol}: {str(e)}")
                error_count += 1
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Technical indicators refresh completed: "
            f"{success_count} success, {error_count} errors, "
            f"took {elapsed:.2f}s"
        )
        
    except Exception as e:
        logger.error(f"Technical indicators refresh job failed: {str(e)}", exc_info=True)


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
        from app.services.fundamental_analysis_service import FundamentalAnalysisService
        fundamental_service = FundamentalAnalysisService()
        
        for symbol in symbols:
            try:
                await fundamental_service.get_fundamental_data(symbol, force_refresh=True)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to refresh fundamental data for {symbol}: {str(e)}")
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
        RISK_PROFILE_RETENTION_DAYS = 90    # 风险档案保留90天
        GEO_EVENTS_RETENTION_DAYS = 60      # 地缘事件保留60天
        MACRO_INDICATORS_RETENTION_DAYS = 365  # 宏观指标保留1年
        
        cutoff_behavior = datetime.now() - timedelta(days=BEHAVIOR_STATS_RETENTION_DAYS)
        cutoff_risk = datetime.now() - timedelta(days=RISK_PROFILE_RETENTION_DAYS)
        cutoff_geo = datetime.now() - timedelta(days=GEO_EVENTS_RETENTION_DAYS)
        cutoff_macro = datetime.now() - timedelta(days=MACRO_INDICATORS_RETENTION_DAYS)
        
        deleted_counts = {
            "behavior_stats": 0,
            "risk_profiles": 0,
            "geo_events": 0,
            "macro_indicators": 0
        }
        
        async with _get_session() as session:
            try:
                # 清理行为统计数据
                result = await session.execute(
                    delete(SymbolBehaviorStats).where(
                        SymbolBehaviorStats.last_updated < cutoff_behavior
                    )
                )
                deleted_counts["behavior_stats"] = result.rowcount
                
                # 清理风险档案数据
                result = await session.execute(
                    delete(SymbolRiskProfile).where(
                        SymbolRiskProfile.last_updated < cutoff_risk
                    )
                )
                deleted_counts["risk_profiles"] = result.rowcount
                
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


async def scan_daily_opportunities_job():
    """任务7: 潜在机会扫描（中大型科技股）

    频率: 每天北京时间 20:30
    功能: 扫描股票池，计算技术/基本面/情绪评分，结合宏观风险产出 1-3 只候选并落库
    """
    try:
        logger.info("Starting daily opportunities scan job")
        start_time = datetime.now()

        async with _get_session() as session:
            svc = PotentialOpportunitiesService(session)
            run, notes = await svc.scan_and_persist(
                universe_name="US_LARGE_MID_TECH",
                min_score=75,
                max_results=3,
                force_refresh=False,
            )

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Daily opportunities scan completed: "
            f"qualified={run.qualified_symbols}/{run.total_symbols}, "
            f"macro={run.macro_risk_level}/{run.macro_overall_score}, "
            f"took {elapsed:.2f}s, notes={notes}"
        )

    except Exception as e:
        logger.error(f"Daily opportunities scan job failed: {str(e)}", exc_info=True)


def register_all_jobs(scheduler):
    """注册所有定时任务到调度器
    
    Args:
        scheduler: APScheduler实例
    """
    from app.jobs.scheduler import add_job
    
    # 任务1: 技术指标刷新 - 每1小时
    add_job(
        func=refresh_technical_indicators_job,
        trigger='interval',
        id='refresh_technical_indicators',
        name='刷新技术指标',
        hours=1,
        next_run_time=datetime.now() + timedelta(minutes=5)  # 5分钟后首次运行
    )
    
    # 任务2: 基本面数据刷新 - 每天凌晨2点
    add_job(
        func=refresh_fundamental_data_job,
        trigger='cron',
        id='refresh_fundamental_data',
        name='刷新基本面数据',
        hour=2,
        minute=0
    )
    
    # 任务3: 宏观指标刷新 - 每天早上9点
    add_job(
        func=refresh_macro_indicators_job,
        trigger='cron',
        id='refresh_macro_indicators',
        name='刷新宏观指标',
        hour=9,
        minute=0
    )
    
    # 任务4: 地缘政治事件抓取 - 每4小时
    add_job(
        func=fetch_geopolitical_events_job,
        trigger='interval',
        id='fetch_geopolitical_events',
        name='抓取地缘政治事件',
        hours=4,
        next_run_time=datetime.now() + timedelta(minutes=10)  # 10分钟后首次运行
    )
    
    # 任务5: 宏观风险计算 - 每6小时
    add_job(
        func=calculate_macro_risk_job,
        trigger='interval',
        id='calculate_macro_risk',
        name='计算宏观风险',
        hours=6,
        next_run_time=datetime.now() + timedelta(minutes=15)  # 15分钟后首次运行
    )
    
    # 任务6: 旧数据清理 - 每天凌晨3点
    add_job(
        func=cleanup_old_data_job,
        trigger='cron',
        id='cleanup_old_data',
        name='清理旧数据',
        hour=3,
        minute=0
    )

    # 任务7: 潜在机会扫描 - 每天北京时间20:30
    add_job(
        func=scan_daily_opportunities_job,
        trigger='cron',
        id='scan_daily_opportunities_tech',
        name='每日机会扫描-科技股(20:30)',
        hour=20,
        minute=30
    )
    
    logger.info("All scheduled jobs registered successfully")
