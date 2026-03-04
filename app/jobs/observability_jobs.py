"""observability_jobs.py — V10.3.3 可观测性定时任务

- 每 5 分钟：因子敞口快照（portfolio_factor_exposure）
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def take_factor_exposure_snapshot() -> None:
    """每 5 分钟采样一次五因子敞口。"""
    from app.models.db import SessionLocal
    from app.services.risk_observability_service import risk_observability_service
    try:
        async with SessionLocal() as db:
            async with db.begin():
                # 需要持仓数据。通过 TradingPlan 读取活跃仓位账户并按用户补快照
                from app.models.trading_plan import TradingPlan
                from sqlalchemy import select, func
                stmt = select(TradingPlan).where(
                    func.upper(TradingPlan.plan_status).in_(["ACTIVE", "PARTIAL"])
                )
                rows = (await db.execute(stmt)).scalars().all()

                if not rows:
                    return

                # 按账户（等价 user_id）分组
                users: set[str] = set()
                for r in rows:
                    if r.account_id:
                        users.add(str(r.account_id))

                for user_id in users:
                    await risk_observability_service.seed_snapshot_from_live_data(db, user_id)
    except Exception as e:
        logger.error("take_factor_exposure_snapshot failed: %s", e)


def register_observability_jobs(scheduler) -> None:
    """注册可观测性定时任务。"""
    scheduler.add_job(
        take_factor_exposure_snapshot,
        trigger="interval",
        minutes=5,
        id="observability_factor_snapshot",
        replace_existing=True,
        name="[V10.3.3] 五因子敞口快照（5min）",
    )
    logger.info("[V10.3.3] Observability jobs registered")
