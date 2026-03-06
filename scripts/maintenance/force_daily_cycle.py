from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import argparse
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("manual_trigger")

async def force_trigger(
    max_signals: int | None = None,
    only_autonomous: bool = False,
    skip_autonomous: bool = False,
):
    from app.jobs.quant_loop_jobs import run_daily_trading_cycle, run_autonomous_decision_cycle

    # 绕过 market_hours 检查的方法是将 is_any_market_active 补丁掉
    # 或者直接调用后续逻辑，但 quant_loop_jobs 里的函数自带了 if not is_any_market_active(): return
    
    # 方案：临时修改环境变量或直接 mock
    import app.jobs.quant_loop_jobs
    from app.services.autonomous_engine import autonomous_engine
    
    # 定义一个永远返回 True 的 mock
    def mock_market_active():
        logger.info("Mocking market active status to FORCE trigger.")
        return True
    
    # 替换掉 job 文件中的引用
    app.jobs.quant_loop_jobs.is_any_market_active = mock_market_active

    # 可选：仅处理前 N 条信号（调试加速）
    original_fetch = autonomous_engine._fetch_pending_signals
    if max_signals and max_signals > 0:
        async def limited_fetch(account_id: str, db):
            rows = await original_fetch(account_id, db)
            limited = rows[:max_signals]
            logger.info(
                f"Debug mode enabled: limiting pending signals {len(rows)} -> {len(limited)} (max={max_signals})"
            )
            return limited

        autonomous_engine._fetch_pending_signals = limited_fetch  # type: ignore[method-assign]
    
    try:
        if not only_autonomous:
            logger.info("Starting MANUALLY triggered daily_trading_cycle...")
            await run_daily_trading_cycle()
        else:
            logger.info("Skipping daily_trading_cycle (--only-autonomous enabled)")

        if not skip_autonomous:
            logger.info("Starting MANUALLY triggered autonomous_decision_cycle...")
            await run_autonomous_decision_cycle()
        else:
            logger.info("Skipping autonomous_decision_cycle (--skip-autonomous enabled)")
        
        logger.info("Manual trigger sequence COMPLETED.")
    finally:
        # 恢复原方法，避免影响其他入口
        autonomous_engine._fetch_pending_signals = original_fetch  # type: ignore[method-assign]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Force trigger daily + autonomous cycles (with optional signal limit)")
    parser.add_argument(
        "--max-signals",
        type=int,
        default=None,
        help="Only process first N pending signals per cycle (debug acceleration).",
    )
    parser.add_argument(
        "--only-autonomous",
        action="store_true",
        help="Run only autonomous_decision_cycle (skip daily_trading_cycle).",
    )
    parser.add_argument(
        "--skip-autonomous",
        action="store_true",
        help="Run only daily_trading_cycle (skip autonomous_decision_cycle).",
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = _parse_args()
    env_max = os.getenv("FORCE_CYCLE_MAX_SIGNALS")
    max_signals = args.max_signals
    if max_signals is None and env_max:
        try:
            max_signals = int(env_max)
        except Exception:
            logger.warning(f"Invalid FORCE_CYCLE_MAX_SIGNALS={env_max!r}, ignored.")

    asyncio.run(
        force_trigger(
            max_signals=max_signals,
            only_autonomous=bool(args.only_autonomous),
            skip_autonomous=bool(args.skip_autonomous),
        )
    )
