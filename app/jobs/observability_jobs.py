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
                # 需要持仓数据。这里通过 TradingPlan 读取活跃仓位
                from app.models.trading_plan import TradingPlan
                from sqlalchemy import select
                stmt = select(TradingPlan).where(
                    TradingPlan.status.in_(["active", "partial"])
                )
                rows = (await db.execute(stmt)).scalars().all()

                if not rows:
                    return

                # 按用户分组
                users: dict[str, list] = {}
                for r in rows:
                    users.setdefault(r.user_id, []).append(r)

                for user_id, positions in users.items():
                    symbol_weights = {
                        p.symbol: float(getattr(p, "market_value", 0) or 0)
                        for p in positions
                    }
                    # 默认 Beta 估算（实际可从 market_data_provider 获取）
                    factor_betas = {
                        p.symbol: {"market": 1.0, "hml": 0.0, "smb": 0.0, "mom": 0.0, "qmj": 0.0}
                        for p in positions
                    }
                    await risk_observability_service.take_snapshot(
                        db,
                        user_id=user_id,
                        symbol_weights=symbol_weights,
                        factor_betas=factor_betas,
                        returns_history=[],  # 简化：生产中读取历史收益序列
                    )
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
