"""
量化交易闭环定时任务
在现有的scheduler系统中添加自动化闭环任务
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.models.db import SessionLocal
from app.engine.quant_trading_loop import QuantTradingLoop
from app.core.config import settings


async def run_daily_trading_cycle():
    """
    每日交易闭环任务
    建议在交易日开盘前运行(生成信号)和收盘后运行(评估和优化)
    """
    async with SessionLocal() as session:
        try:
            loop = QuantTradingLoop(session)
            
            # 运行完整周期
            results = await loop.run_full_cycle(
                account_id=settings.TIGER_ACCOUNT,
                execute_trades=False,  # 默认不自动执行,仅生成信号
                optimize=True
            )
            
            print(f"✅ Daily trading cycle completed at {datetime.utcnow()}")
            print(f"   Signals generated: {results['phases']['signal_generation']['total_signals_generated']}")
            print(f"   Signals validated: {results['phases']['signal_validation']['validated_signals']}")
            
        except Exception as e:
            print(f"❌ Daily trading cycle failed: {str(e)}")


async def run_performance_evaluation():
    """
    每日性能评估任务
    建议在收盘后运行
    """
    async with SessionLocal() as session:
        try:
            from app.engine.performance_analyzer import PerformanceAnalyzer
            
            analyzer = PerformanceAnalyzer(session)
            
            # 评估当日表现
            performance = await analyzer.evaluate_daily_performance(
                account_id=settings.TIGER_ACCOUNT
            )
            
            print(f"✅ Daily performance evaluation completed")
            print(f"   Signals executed: {performance.get('signals_executed', 0)}")
            print(f"   Daily PnL: ${performance.get('daily_pnl', 0):.2f}")
            
        except Exception as e:
            print(f"❌ Performance evaluation failed: {str(e)}")


async def run_adaptive_optimization():
    """
    自适应优化任务
    建议每日或每周运行
    """
    async with SessionLocal() as session:
        try:
            from app.engine.adaptive_optimizer import AdaptiveOptimizer
            
            optimizer = AdaptiveOptimizer(session)
            
            # 运行优化
            results = await optimizer.run_daily_optimization(
                account_id=settings.TIGER_ACCOUNT
            )
            
            print(f"✅ Adaptive optimization completed")
            print(f"   Optimizations: {len(results.get('optimizations', []))}")
            
        except Exception as e:
            print(f"❌ Adaptive optimization failed: {str(e)}")


def register_quant_loop_jobs(scheduler: AsyncIOScheduler):
    """
    注册量化交易闭环定时任务
    
    调用此函数将闭环任务添加到scheduler
    """
    
    # 每日交易周期 - 早上8:00 (市场开盘前)
    scheduler.add_job(
        run_daily_trading_cycle,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_trading_cycle",
        name="Daily Trading Cycle (Signal Generation)",
        replace_existing=True
    )
    
    # 每日性能评估 - 下午6:00 (市场收盘后)
    scheduler.add_job(
        run_performance_evaluation,
        trigger="cron",
        hour=18,
        minute=0,
        id="daily_performance_eval",
        name="Daily Performance Evaluation",
        replace_existing=True
    )
    
    # 自适应优化 - 晚上10:00
    scheduler.add_job(
        run_adaptive_optimization,
        trigger="cron",
        hour=22,
        minute=0,
        id="adaptive_optimization",
        name="Adaptive Optimization",
        replace_existing=True
    )
    
    print("✓ Quantitative Trading Loop jobs registered:")
    print("  - Daily Trading Cycle: 08:00 (Signal Generation)")
    print("  - Performance Evaluation: 18:00 (Post-Market)")
    print("  - Adaptive Optimization: 22:00 (Daily)")
