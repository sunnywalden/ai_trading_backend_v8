"""
统一任务配置同步与执行任务
负责将数据库中的 TaskTriggerConfig 同步到 APScheduler 调度器中，并定义实际执行逻辑。
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.models.db import SessionLocal
from app.models.task_config import TaskTriggerConfig
from app.schemas.task_config import TaskType
from app.core.config import settings

logger = logging.getLogger(__name__)

# 用于标记由配置同步生成的任务前缀
JOB_PREFIX = "dyn_task_"


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
                logger.info(f"[TaskConfig] Config {config_id} is disabled or deleted, skip execution")
                return

            logger.info(f"[TaskConfig] Executing task: {config.name} (Type: {config.task_type})")

            if config.task_type == TaskType.POSITION_EVAL.value:
                from app.services.position_eval_service import PositionEvalService
                from app.schemas.position_eval import TriggerEvalTaskRequest, EvalScope
                
                svc = PositionEvalService(session)
                
                # 构建触发请求
                params = config.params or {}
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
                logger.info(f"[TaskConfig] Running PositionEvalTask {task.id} in background")
                await svc.run_task(account_id, task.id)

            elif config.task_type == TaskType.OPPORTUNITY_SCAN.value:
                # 待实现机会扫描的自动触发逻辑
                logger.warning(f"[TaskConfig] Task type {config.task_type} automatic trigger not implemented yet")
                pass
            
            # 其他任务类型...
            
            logger.info(f"[TaskConfig] Task {config.name} execution triggered successfully")

        except Exception as e:
            logger.error(f"[TaskConfig] Failed to execute configured task {config_id}: {e}", exc_info=True)


async def sync_task_configs_job():
    """
    配置同步任务：扫描数据库中所有已启用的 TaskTriggerConfig，并同步到 APScheduler。
    """
    from app.jobs.scheduler import get_scheduler, add_job, remove_job
    
    logger.info("[TaskConfig] Starting task configurations sync")
    
    async with SessionLocal() as session:
        try:
            stmt = select(TaskTriggerConfig).where(TaskTriggerConfig.enabled == True)
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
