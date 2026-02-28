
import asyncio
import logging
import sys
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db import SessionLocal
from app.jobs.quant_loop_jobs import run_daily_trading_cycle, run_autonomous_decision_cycle

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("manual_trigger")

async def force_trigger():
    # 绕过 market_hours 检查的方法是将 is_any_market_active 补丁掉
    # 或者直接调用后续逻辑，但 quant_loop_jobs 里的函数自带了 if not is_any_market_active(): return
    
    # 方案：临时修改环境变量或直接 mock
    import app.jobs.quant_loop_jobs
    
    # 定义一个永远返回 True 的 mock
    def mock_market_active():
        logger.info("Mocking market active status to FORCE trigger.")
        return True
    
    # 替换掉 job 文件中的引用
    app.jobs.quant_loop_jobs.is_any_market_active = mock_market_active
    
    logger.info("Starting MANUALLY triggered daily_trading_cycle...")
    await run_daily_trading_cycle()
    
    logger.info("Starting MANUALLY triggered autonomous_decision_cycle...")
    # 这个周期会处理我们刚刚拯救的 28 条 VALIDATED 信号
    await run_autonomous_decision_cycle()
    
    logger.info("Manual trigger sequence COMPLETED.")

if __name__ == "__main__":
    asyncio.run(force_trigger())
