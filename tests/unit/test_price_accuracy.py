#!/usr/bin/env python3
"""
快捷交易价格准确性测试脚本
测试场景：
1. 限价单模式（价格获取成功）
2. 市价单模式（价格获取失败）
"""
import asyncio
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.services.quick_trade_service import QuickTradeService

async def test_price_accuracy():
    """测试价格准确性修复"""
    print("=" * 80)
    print("🧪 快捷交易价格准确性测试")
    print("=" * 80)
    
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        service = QuickTradeService(session)
        
        # 测试1: 价格获取方法
        print("\n📊 测试 1: _get_current_price() 方法")
        print("-" * 80)
        
        test_symbols = ["META", "AAPL", "INVALID_SYMBOL"]
        for symbol in test_symbols:
            try:
                price = await service._get_current_price(symbol)
                print(f"✅ {symbol:20} : ${price:10.2f}")
            except Exception as e:
                print(f"❌ {symbol:20} : 抛出异常 - {str(e)[:50]}")
        
        # 测试2: 账户权益获取
        print("\n\n📊 测试 2: _get_account_equity() 方法")
        print("-" * 80)
        try:
            equity = await service._get_account_equity()
            print(f"✅ 账户权益: ${equity:,.2f}")
        except Exception as e:
            print(f"❌ 账户权益获取失败: {e}")
        
        print("\n\n" + "=" * 80)
        print("📝 测试结果说明")
        print("=" * 80)
        print("\n✅ 预期行为:")
        print("   1. 有效 symbol: 返回准确价格（不是默认值 100.0）")
        print("   2. 无效 symbol: 抛出异常（ValueError）")
        print("   3. 账户权益: 返回真实权益或抛出异常")
        
        print("\n❌ 不应出现:")
        print("   1. 价格返回 100.0（默认值）")
        print("   2. 权益返回 1000000.0（默认值）")
        print("   3. 静默失败（无异常但返回错误值）")
        
        print("\n💡 下一步:")
        print("   1. 测试快捷交易预览接口（需要真实的 run_id）")
        print("   2. 验证限价单和市价单两种模式")
        print("   3. 检查前端 UI 显示")

if __name__ == "__main__":
    try:
        asyncio.run(test_price_accuracy())
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
    except Exception as e:
        print(f"\n\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
