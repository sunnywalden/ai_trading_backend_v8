"""
Paper Trading 自动毕业检查任务 (V10.1)

每日 18:05 运行（在每日绩效评估之后），扫描所有活跃策略运行记录，
对符合条件的 paper trading 账户触发自动毕业审核，
并将结果写入 autonomy_audit_log 以供前端展示。
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.core.config import settings
from app.models.db import SessionLocal
from app.models.strategy import StrategyRun

logger = logging.getLogger(__name__)


async def run_paper_graduation_check():
    """
    逐一扫描所有 account_id 下处于 COMPLETED 状态的最新策略运行，
    调用 PaperTradingService.check_graduation() 判断是否达到毕业阈值。
    若 eligible=True，写入审计日志供运营人工复核。
    """
    logger.info("[paper_graduation] Starting daily graduation check …")

    async with SessionLocal() as session:
        try:
            from sqlalchemy import distinct, select

            from app.services.paper_trading_service import PaperTradingService
            svc = PaperTradingService()

            # 取所有有策略运行记录的 account_id
            stmt = select(distinct(StrategyRun.account_id)).where(
                StrategyRun.status == "COMPLETED"
            )
            result = await session.execute(stmt)
            account_ids = [row[0] for row in result.all()]

            eligible_count = 0
            for account_id in account_ids:
                try:
                    # 取该账户最新策略运行
                    run_stmt = (
                        select(StrategyRun)
                        .where(
                            StrategyRun.account_id == account_id,
                            StrategyRun.status == "COMPLETED",
                        )
                        .order_by(StrategyRun.finished_at.desc())
                        .limit(1)
                    )
                    run_result = await session.execute(run_stmt)
                    run = run_result.scalar_one_or_none()
                    if run is None:
                        continue

                    strategy_name = run.strategy.name if run.strategy else "unknown"
                    symbols: list[str] = (
                        [a.symbol for a in run.assets]
                        if run.assets
                        else []
                    )

                    graduation = await svc.check_graduation(
                        account_id=account_id,
                        strategy_name=strategy_name,
                        symbols=symbols,
                        db=session,
                    )

                    if graduation.get("eligible"):
                        eligible_count += 1
                        logger.info(
                            f"[paper_graduation] Account {account_id} / "
                            f"strategy '{strategy_name}' ELIGIBLE for graduation: "
                            f"{graduation.get('message', '')}"
                        )
                        # 写入审计日志（autonomy_audit_log 表）
                        try:
                            from sqlalchemy import text as _text

                            from app.models.autonomy_audit_log import \
                                AutonomyAuditLog
                            await session.execute(
                                _text(
                                    f"INSERT INTO {AutonomyAuditLog.__tablename__} "
                                    "(account_id, event_type, detail, created_at) "
                                    "VALUES (:aid, 'PAPER_GRADUATION_ELIGIBLE', :detail, :ts)"
                                ),
                                {
                                    "aid": account_id,
                                    "detail": str(graduation),
                                    "ts": datetime.utcnow(),
                                },
                            )
                            await session.commit()
                        except Exception as _log_err:
                            logger.warning(
                                f"[paper_graduation] Failed to write audit log for "
                                f"{account_id}: {_log_err}"
                            )
                    else:
                        logger.debug(
                            f"[paper_graduation] Account {account_id} not yet eligible: "
                            f"{graduation.get('message', '')}"
                        )
                except Exception as account_err:
                    logger.error(
                        f"[paper_graduation] Error processing account {account_id}: {account_err}",
                        exc_info=True,
                    )

            logger.info(
                f"[paper_graduation] Graduation check completed — "
                f"scanned={len(account_ids)} eligible={eligible_count}"
            )

        except Exception as e:
            logger.error(f"[paper_graduation] Job failed: {e}", exc_info=True)


def register_paper_graduation_job(scheduler) -> None:
    """将 paper 毕业检查任务挂载到 APScheduler（每日 18:05）。"""
    scheduler.add_job(
        run_paper_graduation_check,
        trigger="cron",
        hour=18,
        minute=5,
        id="paper_graduation_check",
        name="Paper Trading Graduation Check (18:05)",
        replace_existing=True,
    )
    logger.info("✓ Paper graduation check job registered: daily 18:05")
