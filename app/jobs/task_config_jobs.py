"""
统一任务配置同步与执行任务
负责将数据库中的 TaskTriggerConfig 同步到 APScheduler 调度器中，并定义实际执行逻辑。
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select, text

from app.models.db import SessionLocal
from app.models.strategy import Strategy
from app.models.task_config import TaskTriggerConfig
from app.schemas.task_config import TaskType

logger = logging.getLogger(__name__)

# 用于标记由配置同步生成的任务前缀
JOB_PREFIX = "dyn_task_"


async def _run_opportunity_scan(
    session,
    account_id: str,
    params: dict[str, Any],
) -> None:
    from app.jobs.strategy_jobs import (AUTO_UNIVERSE_KEY,
                                        execute_strategy_run_job)
    from app.services.strategy_service import StrategyRunService

    strategy_stmt = (
        select(Strategy)
        .where(Strategy.is_active.is_(True))
        .order_by(desc(Strategy.is_builtin), desc(Strategy.updated_at))
        .limit(1)
    )
    strategy_res = await session.execute(strategy_stmt)
    strategy = strategy_res.scalars().first()
    if not strategy:
        logger.warning(
            "[TaskConfig] Opportunity scan skipped: no active strategy"
        )
        return

    run_svc = StrategyRunService(session)
    target_universe = str(params.get("universe") or AUTO_UNIVERSE_KEY)
    direction = str(params.get("direction") or "LONG")
    min_score = int(params.get("min_score") or 60)
    max_results = int(params.get("max_results") or 30)
    priority = int(params.get("priority") or 10)

    run = await run_svc.create_run(
        strategy=strategy,
        user_id=account_id,
        account_id=account_id,
        direction=direction,
        target_universe=target_universe,
        min_score=min_score,
        max_results=max_results,
        priority=priority,
    )
    await execute_strategy_run_job(run.id, task_id=f"dyn_scan:{run.id}")

    logger.info(
        "[TaskConfig] Opportunity scan completed: run_id=%s strategy=%s universe=%s",
        run.id,
        strategy.name,
        target_universe,
    )


async def _run_data_warmup(session, account_id: str) -> None:
    from app.models.etf_watchlist import EtfWatchlist
    from app.services.dashboard_v2_service import DashboardV2Service
    from app.services.regime_classifier import regime_classifier

    try:
        await regime_classifier.get_current_regime(session)
    except Exception as exc:
        logger.warning("[TaskConfig] Data warmup regime step failed: %s", exc)

    try:
        svc = DashboardV2Service(session)
        await svc.get_full_dashboard(account_id)
    except Exception as exc:
        logger.warning("[TaskConfig] Data warmup dashboard step failed: %s", exc)

    try:
        await session.execute(
            text(
                "SELECT COUNT(*) FROM price_alerts "
                "WHERE alert_status='ACTIVE' LIMIT 1"
            )
        )
    except Exception as exc:
        logger.warning("[TaskConfig] Data warmup alerts step failed: %s", exc)

    try:
        await session.execute(select(EtfWatchlist).limit(10))
    except Exception as exc:
        logger.warning("[TaskConfig] Data warmup ETF pool step failed: %s", exc)

    try:
        await session.execute(
            text(
                "SELECT COUNT(*) FROM trading_signals "
                "WHERE status IN ('GENERATED', 'VALIDATED') LIMIT 1"
            )
        )
    except Exception as exc:
        logger.warning("[TaskConfig] Data warmup signal step failed: %s", exc)

    logger.info("[TaskConfig] Data warmup finished for account=%s", account_id)


async def _run_system_health_check() -> None:
    from app.jobs.m4_health_jobs import autonomy_health_check_job

    await autonomy_health_check_job()
    logger.info("[TaskConfig] System health check finished")


async def execute_configured_task(config_id: int, account_id: str):
    """
    执行由配置触发的任务实例
    """
    async with SessionLocal() as session:
        try:
            # 重新获取最新配置以防在调度期间被禁或修改
            result = await session.execute(
                select(TaskTriggerConfig).where(TaskTriggerConfig.id == config_id)
            )
            config = result.scalar_one_or_none()
            if not config or not config.enabled:
                logger.info(
                    "[TaskConfig] Config %s is disabled or deleted, skip execution",
                    config_id,
                )
                return

            logger.info(
                "[TaskConfig] Executing task: %s (Type: %s)",
                config.name,
                config.task_type,
            )

            params = config.params or {}

            if config.task_type == TaskType.POSITION_EVAL.value:
                from app.schemas.position_eval import (EvalScope,
                                                       TriggerEvalTaskRequest)
                from app.services.position_eval_service import \
                    PositionEvalService
                
                svc = PositionEvalService(session)
                
                # 构建触发请求
                scope_str = params.get("scope", "ALL_POSITIONS")
                try:
                    scope = EvalScope(scope_str)
                except ValueError:
                    scope = EvalScope.ALL_POSITIONS

                req = TriggerEvalTaskRequest(
                    config_id=config.id,
                    scope=scope,
                    symbols=params.get("symbols"),
                    eval_dimensions=params.get("eval_dimensions", ["composite"]),
                    extra_params=params.get("extra_params")
                )
                
                # 创建任务（标记为 scheduler 触发）
                task = await svc.trigger_task(account_id, req)
                # 修改触发方式为 scheduler
                task.triggered_by = "scheduler"
                await session.commit()
                
                # 立即执行
                logger.info(
                    "[TaskConfig] Running PositionEvalTask %s in background",
                    task.id,
                )
                await svc.run_task(account_id, task.id)

            elif config.task_type == TaskType.OPPORTUNITY_SCAN.value:
                await _run_opportunity_scan(session, account_id, params)

            elif config.task_type == TaskType.DATA_WARMUP.value:
                await _run_data_warmup(session, account_id)

            elif config.task_type == TaskType.SYSTEM_HEALTH.value:
                await _run_system_health_check()

            else:
                logger.warning(
                    "[TaskConfig] Unsupported task type: %s",
                    config.task_type,
                )
            
            logger.info(
                "[TaskConfig] Task %s execution triggered successfully",
                config.name,
            )

        except Exception as e:
            logger.error(
                "[TaskConfig] Failed to execute configured task %s: %s",
                config_id,
                e,
                exc_info=True,
            )


async def sync_task_configs_job():
    """
    配置同步任务：扫描数据库中所有已启用的 TaskTriggerConfig，并同步到 APScheduler。
    """
    from app.jobs.scheduler import add_job, get_scheduler, remove_job
    
    logger.info("[TaskConfig] Starting task configurations sync")
    
    async with SessionLocal() as session:
        try:
            stmt = select(TaskTriggerConfig).where(TaskTriggerConfig.enabled.is_(True))
            result = await session.execute(stmt)
            configs = result.scalars().all()
            
            scheduler = get_scheduler()
            current_jobs = scheduler.get_jobs()
            existing_dyn_job_ids = {job.id for job in current_jobs if job.id.startswith(JOB_PREFIX)}
            
            synced_ids = set()
            
            for config in configs:
                job_id = f"{JOB_PREFIX}{config.id}"
                synced_ids.add(job_id)
                
                # 根据配置生成触发器
                trigger = None
                trigger_args = {}
                
                if config.trigger_mode == "DAILY":
                    # trigger_time 格式应为 HH:MM
                    time_parts = (config.trigger_time or "09:00").split(":")
                    if len(time_parts) == 2:
                        trigger = 'cron'
                        trigger_args = {
                            'hour': int(time_parts[0]),
                            'minute': int(time_parts[1])
                        }
                    else:
                        logger.warning(f"[TaskConfig] Invalid DAILY time format for config {config.id}: {config.trigger_time}")
                        continue
                elif config.trigger_mode == "CRON":
                    # 假设是标准 cron 表达式
                    from zoneinfo import ZoneInfo

                    from apscheduler.triggers.cron import CronTrigger
                    try:
                        # 尝试将 trigger_time (HH:MM 或 cron 表达式) 转换为触发器
                        # 如果包含空格且长度为 5，则解析为标准 crontab
                        cron_str = config.trigger_time
                        if cron_str and len(cron_str.split()) == 5:
                            trigger = CronTrigger.from_crontab(cron_str, timezone=ZoneInfo('Asia/Shanghai'))
                        else:
                            # 降级处理为 cron 字符串（如果只是 HH:MM）
                            time_parts = (config.trigger_time or "09:00").split(":")
                            if len(time_parts) == 2:
                                trigger = 'cron'
                                trigger_args = {
                                    'hour': int(time_parts[0]),
                                    'minute': int(time_parts[1])
                                }
                            else:
                                continue
                    except Exception as e:
                        logger.error(f"[TaskConfig] Invalid CRON expression for config {config.id}: {e}")
                        continue
                elif config.trigger_mode == "MANUAL":
                    # 手动模式不进入调度
                    continue
                else:
                    logger.warning(f"[TaskConfig] Unsupported trigger mode for config {config.id}: {config.trigger_mode}")
                    continue

                # 注册或更新任务
                if isinstance(trigger, str):
                    add_job(
                        func=execute_configured_task,
                        trigger=trigger,
                        id=job_id,
                        name=f"Configured Task: {config.name}",
                        replace_existing=True,
                        args=[config.id, config.account_id],
                        **trigger_args
                    )
                else:
                    # 如果是 CronTrigger 实例
                    scheduler.add_job(
                        execute_configured_task,
                        trigger=trigger,
                        id=job_id,
                        name=f"Configured Task: {config.name}",
                        replace_existing=True,
                        args=[config.id, config.account_id]
                    )

            # 清理已经删除或停用的任务
            to_remove = existing_dyn_job_ids - synced_ids
            for rid in to_remove:
                remove_job(rid)
                
            logger.info(f"[TaskConfig] Sync completed. {len(synced_ids)} active dynamic jobs.")
            
        except Exception as e:
            logger.error(f"[TaskConfig] Sync job failed: {e}", exc_info=True)


def register_task_config_jobs(scheduler):
    """
    注册配置同步任务本身
    """
    from app.jobs.scheduler import add_job

    # 每 5 分钟同步一次配置
    add_job(
        func=sync_task_configs_job,
        trigger='interval',
        id='sync_task_trigger_configs',
        name='同步数据库任务配置',
        minutes=5,
        next_run_time=datetime.now() # 立即执行第一次
    )
