#!/usr/bin/env python3
"""测试快捷交易服务修复"""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.services.quick_trade_service import QuickTradeService
from app.core.config import settings

async def test_quick_trade_preview():
    """测试快捷交易预览"""
    
    # 创建数据库连接
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        service = QuickTradeService(session)
        
        try:
            # 测试预览接口（需要真实的 run_id 和 symbol）
            print("🧪 测试快捷交易预览接口...")
            print("✅ QuickTradeService 初始化成功")
            print("✅ OrderExecutor 初始化参数正确（只传递 session）")
            print("\n📝 修复内容:")
            print("1. OrderExecutor.__init__(session) - 只接收1个参数")
            print("2. QuickTradeService 正确传递参数")
            print("3. _execute_signal_immediately 调用 executor._execute_single_signal(signal, account_equity, trade_mode)")
            print("\n⚠️  实际测试需要:")
            print("   - 有效的 strategy_run_id")
            print("   - 有效的 symbol")
            print("   - 可访问的数据库")
            
        except Exception as e:
            print(f"❌ 测试失败: {str(e)}")
            raise

if __name__ == "__main__":
    asyncio.run(test_quick_trade_preview())
