"""
V10.4 M4 自主循环健康监控任务

每 2 分钟运行 8 项健康检查，结果写入 Redis 并通过 WebSocket 推送。
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Redis key
_HEALTH_CACHE_KEY = "v10_4:autonomy_health:latest"
_HEALTH_CACHE_TTL = 300   # 5 分钟


async def autonomy_health_check_job() -> None:
    """
    每 2 分钟执行全量系统健康检查。

    1. 从数据库读取各项指标
    2. 生成 AutonomyHealthReport
    3. 写入 Redis（供 API 快速返回）
    4. 通过 WebSocket 广播（可选，若 WebSocket 管理器可用）
    """
    from app.models.db import SessionLocal
    from app.services.autonomy_health_monitor import autonomy_health_monitor

    try:
        async with SessionLocal() as db:
            report = await autonomy_health_monitor.run_all_checks(db)

        report_dict = report.to_dict()

        # ── 写入 Redis ──────────────────────────────────────────
        try:
            from app.models.db import redis_client
            if redis_client:
                await redis_client.setex(
                    _HEALTH_CACHE_KEY,
                    _HEALTH_CACHE_TTL,
                    json.dumps(report_dict, ensure_ascii=False),
                )
        except Exception as exc:
            logger.debug(f"[M4 Health] Redis 写入失败（非致命）: {exc}")

        # ── WebSocket 广播 ──────────────────────────────────────
        try:
            from app.routers.websocket import manager as ws_manager
            await ws_manager.broadcast("autonomy_health", report_dict)
        except Exception:
            pass  # WebSocket 不可用时静默跳过

        level = "WARNING" if report.overall_status != "OK" else "DEBUG"
        getattr(logger, level.lower())(
            "[M4 Health] 检查完成 | 总状态: %s | CRITICAL: %d | WARN: %d",
            report.overall_status,
            sum(1 for c in report.checks if c.status == "CRITICAL"),
            sum(1 for c in report.checks if c.status in ("WARN", "ERROR")),
        )

    except Exception as exc:
        logger.error("[M4 Health] 任务异常: %s", exc, exc_info=True)


def register_m4_jobs(scheduler) -> None:
    """注册 V10.4 M4 自主循环健康监控任务。"""
    from app.jobs.scheduler import add_job
    from datetime import datetime, timedelta

    add_job(
        func=autonomy_health_check_job,
        trigger="interval",
        id="m4_autonomy_health_check",
        name="[V10.4 M4] 自主循环 8 项健康检查（2min）",
        minutes=2,
        next_run_time=datetime.now() + timedelta(seconds=30),
    )
    logger.info("[M4 Jobs] AutonomyHealthCheckJob 已注册 (interval 2min)")
