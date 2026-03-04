"""observability_jobs.py — V10.4 可观测性定时任务

- 每 5 分钟：因子敞口快照（portfolio_factor_exposure）
  V10.4 M1 T1.3 修复：无活跃持仓时也对历史用户写零快照，确保 IC 计算不漂移
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def take_factor_exposure_snapshot() -> None:
    """每 5 分钟采样一次五因子敞口。

    V10.4 T1.3 修复：
      - 有活跃持仓 → 对所有活跃账户写实时快照（原有逻辑）
      - 无活跃持仓 → 对历史出现过的所有账户写零快照，
        确保 IC 时序连续，不因账户空仓期断档导致统计偏移
    """
    from app.models.db import SessionLocal
    from app.services.risk_observability_service import risk_observability_service
    try:
        async with SessionLocal() as db:
            async with db.begin():
                from app.models.trading_plan import TradingPlan
                from sqlalchemy import select, func, distinct

                # ─── 1. 查询当前活跃持仓账户 ───
                stmt_active = select(TradingPlan).where(
                    func.upper(TradingPlan.plan_status).in_(["ACTIVE", "PARTIAL"])
                )
                rows = (await db.execute(stmt_active)).scalars().all()

                if rows:
                    # 有活跃持仓：按账户写实时快照（原有逻辑）
                    users: set[str] = set()
                    for r in rows:
                        if r.account_id:
                            users.add(str(r.account_id))
                    for user_id in users:
                        await risk_observability_service.seed_snapshot_from_live_data(db, user_id)
                else:
                    # ─── 2. V10.4 T1.3: 无活跃持仓 → 写零快照 ───
                    stmt_all = select(distinct(TradingPlan.account_id)).where(
                        TradingPlan.account_id.isnot(None)
                    )
                    all_account_ids = [row[0] for row in (await db.execute(stmt_all)).fetchall()]

                    if all_account_ids:
                        logger.debug(
                            "[ObsJobs] 无活跃持仓，对 %d 个历史账户写零快照",
                            len(all_account_ids),
                        )
                        for user_id in all_account_ids:
                            try:
                                await risk_observability_service.seed_snapshot_from_live_data(
                                    db, user_id
                                )
                            except Exception as exc:
                                logger.warning(
                                    "[ObsJobs] 账户 %s 零快照写入失败: %s", user_id, exc
                                )
                    else:
                        logger.debug("[ObsJobs] 无任何历史账户，跳过本次快照")

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
        name="[V10.4 M1] 五因子敞口快照（5min）",
    )
    logger.info("[V10.4 M1] Observability jobs registered")
