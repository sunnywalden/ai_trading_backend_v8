"""equity_jobs.py — 账户权益快照定时任务

- 每个美股交易日收盘后（16:10 ET）写入当日 equity_snapshot
"""

from __future__ import annotations

import logging
from typing import Set

from sqlalchemy import distinct, select

from app.models.db import SessionLocal
from app.models.equity_snapshot import EquitySnapshot
from app.models.trade_pnl_attribution import TradePnlAttribution
from app.models.trading_plan import TradingPlan
from app.models.trading_signal import TradingSignal
from app.services.equity_service import EquityService
from app.broker.factory import make_option_broker_client

logger = logging.getLogger(__name__)


async def take_daily_equity_snapshot() -> None:
    """写入当日权益快照（按账户）。"""
    accounts: Set[str] = set()

    # 1) 当前券商账户（优先）
    try:
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            accounts.add(str(broker_id))
    except Exception as e:
        logger.warning("[EquityJobs] resolve broker account failed: %s", e)

    # 2) 历史出现过的账户（防止漏写）
    try:
        async with SessionLocal() as db:
            stmt_plan = select(distinct(TradingPlan.account_id)).where(TradingPlan.account_id.isnot(None))
            stmt_signal = select(distinct(TradingSignal.account_id)).where(TradingSignal.account_id.isnot(None))
            stmt_pnl = select(distinct(TradePnlAttribution.account_id)).where(TradePnlAttribution.account_id.isnot(None))
            stmt_snapshot = select(distinct(EquitySnapshot.account_id)).where(EquitySnapshot.account_id.isnot(None))

            for stmt in (stmt_plan, stmt_signal, stmt_pnl, stmt_snapshot):
                rows = (await db.execute(stmt)).all()
                for row in rows:
                    if row[0]:
                        accounts.add(str(row[0]))
    except Exception as e:
        logger.warning("[EquityJobs] resolve historical accounts failed: %s", e)

    if not accounts:
        logger.info("[EquityJobs] no accounts found, skip daily snapshot")
        return

    success = 0
    failed = 0

    async with SessionLocal() as db:
        svc = EquityService(db)
        for account_id in sorted(accounts):
            try:
                snap = await svc.create_daily_snapshot(account_id)
                success += 1
                logger.info(
                    "[EquityJobs] snapshot ok account=%s date=%s equity=%.2f",
                    account_id,
                    snap.snapshot_date,
                    float(snap.total_equity or 0.0),
                )
            except Exception as e:
                failed += 1
                logger.error("[EquityJobs] snapshot failed account=%s err=%s", account_id, e)

    logger.info("[EquityJobs] daily snapshot done success=%d failed=%d", success, failed)


def register_equity_jobs(scheduler) -> None:
    """注册权益快照任务：每个美股交易日收盘后执行。"""
    from app.jobs.scheduler import add_job

    # 16:10 America/New_York（周一~周五）
    add_job(
        func=take_daily_equity_snapshot,
        trigger="cron",
        id="equity_daily_snapshot_eod_us",
        name="[V10] Equity Daily Snapshot (US EOD)",
        day_of_week="mon-fri",
        hour=16,
        minute=10,
        timezone="America/New_York",
    )
    logger.info("[EquityJobs] registered: 16:10 America/New_York, mon-fri")
