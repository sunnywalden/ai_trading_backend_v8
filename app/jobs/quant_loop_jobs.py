"""
量化交易闭环定时任务
在现有的scheduler系统中添加自动化闭环任务

市场时段守卫：所有交易型任务（信号生成、持仓扫描）仅在对应市场
活跃时段（包含盘前/盘中/盘后）内触发；评估与优化任务不受时段限制。
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.models.db import SessionLocal
from app.engine.quant_trading_loop import QuantTradingLoop
from app.core.config import settings
from app.core.market_hours import is_any_market_active

logger = logging.getLogger(__name__)


async def run_daily_trading_cycle():
    """
    每日交易闭环任务：机会扫描 + 信号生成。
    建议在交易日开盘前运行（默认 08:00）。
    市场时段守卫：若美股和港股均不在活跃时段，则跳过。
    """
    if not is_any_market_active():
        logger.debug("[quant_jobs] run_daily_trading_cycle: market inactive, skip")
        return

    async with SessionLocal() as session:
        try:
            loop = QuantTradingLoop(session)

            results = await loop.run_full_cycle(
                account_id=settings.TIGER_ACCOUNT,
                execute_trades=False,  # 默认不自动执行，仅生成信号
                optimize=True
            )

            signals_gen = results['phases']['signal_generation']['total_signals_generated']
            signals_val = results['phases']['signal_validation']['validated_signals']
            logger.info(
                f"[quant_jobs] Daily trading cycle OK — "
                f"generated={signals_gen} validated={signals_val}"
            )
        except Exception as e:
            logger.error(f"[quant_jobs] Daily trading cycle FAILED: {e}", exc_info=True)


async def run_performance_evaluation():
    """
    每日性能评估任务。
    收盘后运行（默认 18:00），不受市场时段限制。
    """
    async with SessionLocal() as session:
        try:
            from app.engine.performance_analyzer import PerformanceAnalyzer

            analyzer = PerformanceAnalyzer(session)
            performance = await analyzer.evaluate_daily_performance(
                account_id=settings.TIGER_ACCOUNT
            )

            logger.info(
                f"[quant_jobs] Performance eval OK — "
                f"executed={performance.get('signals_executed', 0)} "
                f"pnl=${performance.get('daily_pnl', 0):.2f}"
            )
        except Exception as e:
            logger.error(f"[quant_jobs] Performance evaluation FAILED: {e}", exc_info=True)


async def run_adaptive_optimization():
    """
    自适应优化任务（默认 22:00）。
    不受市场时段限制。
    """
    async with SessionLocal() as session:
        try:
            from app.engine.adaptive_optimizer import AdaptiveOptimizer

            optimizer = AdaptiveOptimizer(session)
            results = await optimizer.run_daily_optimization(
                account_id=settings.TIGER_ACCOUNT
            )

            logger.info(
                f"[quant_jobs] Adaptive optimization OK — "
                f"opts={len(results.get('optimizations', []))}"
            )
        except Exception as e:
            logger.error(f"[quant_jobs] Adaptive optimization FAILED: {e}", exc_info=True)


async def run_position_exit_scan():
    """
    主动持仓监控：止损 / 止盈 / 超龄持仓检测，写入 EXIT 信号。
    每 POSITION_MONITOR_INTERVAL_MINUTES 分钟触发一次（默认 15 分钟）。
    市场时段守卫：若市场均不在活跃时段，跳过本次扫描。
    """
    if not is_any_market_active():
        logger.debug("[quant_jobs] run_position_exit_scan: market inactive, skip")
        return

    async with SessionLocal() as session:
        try:
            from app.engine.position_monitor import PositionMonitor

            monitor = PositionMonitor(session)
            result = await monitor.scan(account_id=settings.TIGER_ACCOUNT)

            logger.info(
                f"[quant_jobs] Position scan OK — "
                f"scanned={result['scanned_positions']} "
                f"exit_signals={result['exit_signals_generated']} "
                f"skipped_no_market={result['skipped_no_market']}"
            )
            if result["details"]:
                for d in result["details"]:
                    logger.info(
                        f"  ↳ {d['symbol']} reason={d.get('reason')} "
                        f"pnl={d.get('pnl_pct', 0):.2%} "
                        f"days={d.get('holding_days')}"
                    )
        except Exception as e:
            logger.error(f"[quant_jobs] Position exit scan FAILED: {e}", exc_info=True)


def register_quant_loop_jobs(scheduler: AsyncIOScheduler):
    """
    注册量化交易闭环定时任务，挂载到 APScheduler。

    任务列表：
      ① 08:00 cron  — 每日交易周期（信号生成，市场时段守卫）
      ② 18:00 cron  — 每日性能评估（不受时段限制）
      ③ 22:00 cron  — 自适应优化   （不受时段限制）
      ④ interval    — 持仓监控扫描（每 N 分钟，市场时段守卫）
    """

    # ① 每日交易周期 — 早上 8:00（市场开盘前，有守卫防止非交易日执行）
    scheduler.add_job(
        run_daily_trading_cycle,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_trading_cycle",
        name="Daily Trading Cycle (Signal Generation)",
        replace_existing=True,
    )

    # ② 每日性能评估 — 下午 6:00（市场收盘后）
    scheduler.add_job(
        run_performance_evaluation,
        trigger="cron",
        hour=18,
        minute=0,
        id="daily_performance_eval",
        name="Daily Performance Evaluation",
        replace_existing=True,
    )

    # ③ 自适应优化 — 晚上 10:00
    scheduler.add_job(
        run_adaptive_optimization,
        trigger="cron",
        hour=22,
        minute=0,
        id="adaptive_optimization",
        name="Adaptive Optimization",
        replace_existing=True,
    )

    # ④ 主动持仓扫描 — 每 N 分钟（默认 15 分钟，市场时段守卫）
    scheduler.add_job(
        run_position_exit_scan,
        trigger="interval",
        minutes=settings.POSITION_MONITOR_INTERVAL_MINUTES,
        id="position_exit_scan",
        name=f"Position Exit Scan (every {settings.POSITION_MONITOR_INTERVAL_MINUTES}m)",
        replace_existing=True,
    )

    logger.info("✓ Quantitative Trading Loop jobs registered:")
    logger.info("  ① Daily Trading Cycle:    08:00  (Signal Generation, market guard)")
    logger.info("  ② Performance Evaluation: 18:00  (Post-Market)")
    logger.info("  ③ Adaptive Optimization:  22:00  (Daily)")
    logger.info(f" ④ Position Exit Scan:    every {settings.POSITION_MONITOR_INTERVAL_MINUTES}m  (market guard)")
