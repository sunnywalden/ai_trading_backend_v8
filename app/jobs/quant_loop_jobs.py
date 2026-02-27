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
    每日交易闭环任务：信号生成 + 验证，并按自主级别决定是否自动执行。
    美股：08:00 触发（盘前信号扫描）；并在盘中每 30 分钟额外触发一次。
    市场时段守卫：若美股和港股均不在活跃时段，则跳过。
    """
    if not is_any_market_active():
        logger.debug("[quant_jobs] run_daily_trading_cycle: market inactive, skip")
        return

    from app.core.runtime_config import get_autonomy_level

    level = await get_autonomy_level()
    # ADVISORY 模式下不自动执行交易，仅生成和验证信号
    should_execute = level in ("FULL", "SEMI")

    async with SessionLocal() as session:
        try:
            loop = QuantTradingLoop(session)

            results = await loop.run_full_cycle(
                account_id=settings.TIGER_ACCOUNT,
                execute_trades=should_execute,
                optimize=True
            )

            signals_gen = results['phases']['signal_generation']['total_signals_generated']
            signals_val = results['phases']['signal_validation']['validated_signals']
            exec_phase  = results['phases'].get('trade_execution', {})
            executed    = exec_phase.get('executed', 0)
            logger.info(
                f"[quant_jobs] Daily trading cycle OK — "
                f"level={level} generated={signals_gen} validated={signals_val} executed={executed}"
            )
        except Exception as e:
            logger.error(f"[quant_jobs] Daily trading cycle FAILED: {e}", exc_info=True)


async def run_autonomous_decision_cycle():
    """
    自主决策周期：每 30 分钟触发，让 AutonomousEngine 处理待执行信号。
    这是真正触发自动下单的入口。
    市场时段守卫：若市场均关闭则跳过。
    """
    if not is_any_market_active():
        logger.debug("[quant_jobs] run_autonomous_decision_cycle: market inactive, skip")
        return

    from app.services.autonomous_engine import autonomous_engine
    from app.models.db import SessionLocal as _SL

    async with _SL() as session:
        try:
            results = await autonomous_engine.run_decision_cycle(
                account_id=settings.TIGER_ACCOUNT,
                db=session
            )
            executed  = sum(1 for r in results if r.get("order_id"))
            blocked   = sum(1 for r in results if not r.get("gate_passed"))
            cb_active = any(r.get("circuit_breaker") for r in results)
            logger.info(
                f"[quant_jobs] Autonomous cycle OK — decisions={len(results)} "
                f"executed={executed} blocked={blocked} circuit_breaker={cb_active}"
            )
        except Exception as e:
            logger.error(f"[quant_jobs] Autonomous decision cycle FAILED: {e}", exc_info=True)


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


async def run_position_rebalance_scan():
    """
    持仓再平衡扫描：读取持仓评分，将 REDUCE/SELL 建议转为 REDUCE/EXIT 信号。
    每小时触发一次，市场时段内有效。
    这是将 AI 减仓/清仓建议转化为可执行信号的关键一步。
    """
    if not is_any_market_active():
        logger.debug("[quant_jobs] run_position_rebalance_scan: market inactive, skip")
        return

    async with SessionLocal() as session:
        try:
            from app.engine.position_rebalance_monitor import PositionRebalanceMonitor

            monitor = PositionRebalanceMonitor(session)
            result = await monitor.scan(account_id=settings.TIGER_ACCOUNT)

            if result["reduce_signals"] + result["exit_signals"] > 0:
                logger.info(
                    f"[quant_jobs] Rebalance scan OK — "
                    f"scanned={result['scanned']} "
                    f"reduce_signals={result['reduce_signals']} "
                    f"exit_signals={result['exit_signals']}"
                )
                for d in result.get("details", []):
                    logger.info(
                        f"  ↳ {d['symbol']} score={d.get('score')} "
                        f"rec={d.get('recommendation')} signal={d.get('signal_created')}"
                    )
        except Exception as e:
            logger.error(f"[quant_jobs] Position rebalance scan FAILED: {e}", exc_info=True)


def register_quant_loop_jobs(scheduler: AsyncIOScheduler):
    """
    注册量化交易闭环定时任务，挂载到 APScheduler。

    任务列表：
      ① 08:00 cron  — 每日交易周期（信号生成 + 按自主级别执行）
      ② interval/30m— 自主决策周期（AutonomousEngine，市场时段守卫）
      ③ 18:00 cron  — 每日性能评估（不受时段限制）
      ④ 22:00 cron  — 自适应优化   （不受时段限制）
      ⑤ interval/15m— 持仓监控扫描（止损/止盈/超龄，市场时段守卫）
      ⑥ interval/60m— 持仓再平衡扫描（REDUCE/SELL建议转信号，市场时段守卫）
    """

    # ① 每日交易周期 — 早上 8:00
    scheduler.add_job(
        run_daily_trading_cycle,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_trading_cycle",
        name="Daily Trading Cycle (Signal Gen + Execute by Level)",
        replace_existing=True,
    )

    # ② 自主决策周期 — 每 30 分钟（盘中信号执行的核心驱动器）
    scheduler.add_job(
        run_autonomous_decision_cycle,
        trigger="interval",
        minutes=30,
        id="autonomous_decision_cycle",
        name="Autonomous Decision Cycle (every 30m, market guard)",
        replace_existing=True,
    )

    # ③ 每日性能评估 — 下午 6:00（市场收盘后）
    scheduler.add_job(
        run_performance_evaluation,
        trigger="cron",
        hour=18,
        minute=0,
        id="daily_performance_eval",
        name="Daily Performance Evaluation",
        replace_existing=True,
    )

    # ④ 自适应优化 — 晚上 10:00
    scheduler.add_job(
        run_adaptive_optimization,
        trigger="cron",
        hour=22,
        minute=0,
        id="adaptive_optimization",
        name="Adaptive Optimization",
        replace_existing=True,
    )

    # ⑤ 主动持仓扫描 — 每 N 分钟（默认 15 分钟，市场时段守卫）
    scheduler.add_job(
        run_position_exit_scan,
        trigger="interval",
        minutes=settings.POSITION_MONITOR_INTERVAL_MINUTES,
        id="position_exit_scan",
        name=f"Position Exit Scan (every {settings.POSITION_MONITOR_INTERVAL_MINUTES}m)",
        replace_existing=True,
    )

    # ⑥ 持仓再平衡扫描 — 每 60 分钟（REDUCE/SELL 建议 → TradingSignal）
    scheduler.add_job(
        run_position_rebalance_scan,
        trigger="interval",
        minutes=60,
        id="position_rebalance_scan",
        name="Position Rebalance Scan (every 60m, market guard)",
        replace_existing=True,
    )

    logger.info("✓ Quantitative Trading Loop jobs registered:")
    logger.info("  ① Daily Trading Cycle:       08:00  (Signal Gen + Execute by Autonomy Level)")
    logger.info("  ② Autonomous Decision Cycle: every 30m  (market guard, core auto-trade driver)")
    logger.info("  ③ Performance Evaluation:    18:00  (Post-Market)")
    logger.info("  ④ Adaptive Optimization:     22:00  (Daily)")
    logger.info(f" ⑤ Position Exit Scan:        every {settings.POSITION_MONITOR_INTERVAL_MINUTES}m  (market guard)")
    logger.info("  ⑥ Position Rebalance Scan:   every 60m  (REDUCE/SELL → Signal, market guard)")
