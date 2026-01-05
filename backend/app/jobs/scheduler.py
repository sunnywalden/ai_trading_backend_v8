"""
APScheduler 调度器配置和初始化

负责管理所有定时任务的调度和执行
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
import logging
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 全局调度器实例
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """获取调度器实例"""
    global _scheduler
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized. Call init_scheduler() first.")
    return _scheduler


def init_scheduler() -> AsyncIOScheduler:
    """初始化调度器
    
    配置:
    - 使用 AsyncIOScheduler 支持异步任务
    - MemoryJobStore 存储任务信息
    - AsyncIOExecutor 执行异步任务
    - 最多10个并发任务
    """
    global _scheduler
    
    if _scheduler is not None:
        logger.warning("Scheduler already initialized")
        return _scheduler
    
    # 配置调度器
    jobstores = {
        'default': MemoryJobStore()
    }
    
    executors = {
        'default': AsyncIOExecutor()
    }
    
    job_defaults = {
        'coalesce': True,  # 合并错过的任务
        'max_instances': 10,  # 最多10个并发任务实例
        'misfire_grace_time': 300  # 错过任务的容忍时间（秒）
    }
    
    _scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone='Asia/Shanghai'
    )
    
    logger.info("Scheduler initialized successfully")
    return _scheduler


def start_scheduler():
    """启动调度器"""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")
    else:
        logger.warning("Scheduler already running")


def shutdown_scheduler(wait: bool = True):
    """关闭调度器
    
    Args:
        wait: 是否等待所有任务完成
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=wait)
        logger.info("Scheduler shut down")
        _scheduler = None


def add_job(
    func,
    trigger,
    id: str,
    name: str,
    replace_existing: bool = True,
    **trigger_args
):
    """添加定时任务
    
    Args:
        func: 要执行的函数
        trigger: 触发器类型 ('interval', 'cron')
        id: 任务唯一标识
        name: 任务名称
        replace_existing: 是否替换已存在的同名任务
        **trigger_args: 触发器参数
    """
    scheduler = get_scheduler()
    
    try:
        scheduler.add_job(
            func,
            trigger=trigger,
            id=id,
            name=name,
            replace_existing=replace_existing,
            **trigger_args
        )
        logger.info(f"Job added: {name} (ID: {id})")
    except Exception as e:
        logger.error(f"Failed to add job {name}: {str(e)}")
        raise


def remove_job(job_id: str):
    """移除定时任务"""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Job removed: {job_id}")
    except Exception as e:
        logger.error(f"Failed to remove job {job_id}: {str(e)}")


def pause_job(job_id: str):
    """暂停定时任务"""
    scheduler = get_scheduler()
    try:
        scheduler.pause_job(job_id)
        logger.info(f"Job paused: {job_id}")
    except Exception as e:
        logger.error(f"Failed to pause job {job_id}: {str(e)}")


def resume_job(job_id: str):
    """恢复定时任务"""
    scheduler = get_scheduler()
    try:
        scheduler.resume_job(job_id)
        logger.info(f"Job resumed: {job_id}")
    except Exception as e:
        logger.error(f"Failed to resume job {job_id}: {str(e)}")


def get_jobs():
    """获取所有任务信息"""
    scheduler = get_scheduler()
    jobs = scheduler.get_jobs()
    return [
        {
            'id': job.id,
            'name': job.name,
            'next_run_time': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None,
            'trigger': str(job.trigger)
        }
        for job in jobs
    ]


def get_job(job_id: str):
    """获取指定任务对象（不存在则返回 None）。"""
    scheduler = get_scheduler()
    return scheduler.get_job(job_id)


def reschedule_job(job_id: str, cron_expr: str, timezone: str = "Asia/Shanghai"):
    """按 Linux crontab 表达式重设指定任务的触发时间。

    说明：
    - cron_expr 必须为 5 段格式：minute hour day month day_of_week
    - timezone 用于解释 cron_expr（默认 Asia/Shanghai）
    """
    scheduler = get_scheduler()

    if not cron_expr or not cron_expr.strip():
        raise ValueError("cron_expr is required")

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(
            "cron_expr must be Linux crontab 5-field format: 'min hour day month dow'"
        )

    tz = ZoneInfo(timezone)
    trigger = CronTrigger.from_crontab(cron_expr.strip(), timezone=tz)

    job = scheduler.get_job(job_id)
    if not job:
        raise ValueError(f"job not found: {job_id}")

    scheduler.reschedule_job(job_id, trigger=trigger)
    logger.info(f"Job rescheduled: {job_id}, cron='{cron_expr}', tz='{timezone}'")
