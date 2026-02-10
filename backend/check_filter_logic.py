
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.core.config import settings
import json

# 必须导入所有模型以解决 SQLAlchemy 关联
from app.models.strategy import Strategy
from app.models.trading_signal import TradingSignal, SignalStatus
from app.models.trading_plan import TradingPlan
from app.models.trade_journal import TradeJournal
from app.models.price_alert import PriceAlert, AlertHistory
from app.models.equity_snapshot import EquitySnapshot
from app.engine.signal_position_filter import SignalPositionFilter

async def check_filter_effect():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # 1. 获取所有信号
        stmt = select(TradingSignal).where(TradingSignal.status == SignalStatus.VALIDATED)
        result = await session.execute(stmt)
        signals = result.scalars().all()
        print(f"当前待执行信号总数: {len(signals)}")
        
        # 2. 打印原始信号详情
        print("\n--- 原始信号详情 ---")
        for s in signals:
            print(f"标的: {s.symbol} | 建议数量: {s.suggested_quantity} | 方向: {s.direction}")
            
        # 3. 模拟运行过滤器
        try:
            filter_svc = SignalPositionFilter(session)
            # 我们假设 account_id 是配置中的
            account_id = settings.TIGER_ACCOUNT
            
            filtered_signals, stats = await filter_svc.filter_signals_with_positions(signals, account_id)
            
            print("\n--- 过滤效果统计 ---")
            print(json.dumps(stats, indent=2, ensure_ascii=False))
            
            print("\n--- 信号类型推断详情 ---")
            for s in signals:
                pos_info = s.extra_metadata.get("current_position", "无") if s.extra_metadata else "无"
                filter_reason = s.extra_metadata.get("filter_reason", "通过") if s.extra_metadata else "通过"
                print(f"标的: {s.symbol} | 类型: {s.signal_type} | 方向: {s.direction} | 持仓信息: {pos_info} | 过滤结果: {filter_reason}")
                
        except Exception as e:
            print(f"执行过滤检查时出错: {e}")

if __name__ == "__main__":
    asyncio.run(check_filter_effect())
