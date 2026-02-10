"""
量化交易闭环服务层

封装闭环引擎的业务逻辑,供API和任务调用
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.quant_trading_loop import QuantTradingLoop
from app.engine.signal_engine import SignalEngine
from app.engine.order_executor import OrderExecutor
from app.engine.performance_analyzer import PerformanceAnalyzer
from app.engine.adaptive_optimizer import AdaptiveOptimizer


class QuantLoopService:
    """量化交易闭环服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.loop = QuantTradingLoop(session)
        self.signal_engine = SignalEngine(session)
        self.executor = OrderExecutor(session)
        self.analyzer = PerformanceAnalyzer(session)
        self.optimizer = AdaptiveOptimizer(session)
    
    async def run_full_cycle(
        self,
        account_id: str,
        execute_trades: bool = False,
        optimize: bool = True
    ) -> Dict[str, Any]:
        """运行完整交易周期"""
        return await self.loop.run_full_cycle(
            account_id=account_id,
            execute_trades=execute_trades,
            optimize=optimize
        )
    
    async def get_system_status(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """获取系统整体状态"""
        status = await self.loop.get_loop_status(account_id)
        
        # 補充更多统计信息
        from app.models.trading_signal import TradingSignal
        from sqlalchemy import select, func
        
        # 今日信号统计
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(func.count())
            .select_from(TradingSignal)
            .where(
                TradingSignal.account_id == account_id,
                TradingSignal.generated_at >= today_start
            )
        )
        result = await self.session.execute(stmt)
        today_signals = result.scalar()
        
        status["today_signals_generated"] = today_signals
        
        return status
    
    async def get_performance_summary(
        self,
        account_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """获取性能摘要"""
        
        # 获取改进机会
        opportunities = await self.analyzer.identify_improvement_opportunities(
            account_id=account_id,
            days=days
        )
        
        # 获取每日性能
        daily_perf = await self.analyzer.evaluate_daily_performance(
            account_id=account_id
        )
        
        return {
            "daily_performance": daily_perf,
            "improvement_opportunities": opportunities,
            "period_days": days
        }
    
    async def execute_top_signals(
        self,
        account_id: str,
        max_orders: int = 3,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """执行优先级最高的信号"""
        
        from app.core.trade_mode import TradeMode
        trade_mode = TradeMode.DRY_RUN if dry_run else TradeMode.LIVE
        
        return await self.executor.execute_signal_batch(
            account_id=account_id,
            max_orders=max_orders,
            trade_mode=trade_mode
        )
