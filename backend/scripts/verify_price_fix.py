#!/usr/bin/env python3
"""验证快捷交易价格修复"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# 添加项目路径
sys.path.insert(0, '/Users/admin/IdeaProjects/ai_trading_backend_v8/backend')

from app.core.config import settings
from app.services.quick_trade_service import QuickTradeService
from app.providers.market_data_provider import MarketDataProvider

async def test_price_fix():
    """测试价格获取修复"""
    print("=" * 80)
    print("🧪 测试快捷交易价格修复")
    print("=" * 80)
    
    # 测试 1: 直接测试 MarketDataProvider
    print("\n📊 测试 1: MarketDataProvider.get_current_price()")
    print("-" * 80)
    provider = MarketDataProvider()
    
    test_symbols = ["META", "AAPL", "TSLA"]
    for symbol in test_symbols:
        try:
            price = await provider.get_current_price(symbol)
            if price > 0 and price != 100.0:
                print(f"✅ {symbol:8} : ${price:10.2f}  (成功)")
            elif price == 100.0:
                print(f"⚠️  {symbol:8} : ${price:10.2f}  (默认值 - API可能失败)")
            else:
                print(f"❌ {symbol:8} : ${price:10.2f}  (失败)")
        except Exception as e:
            print(f"❌ {symbol:8} : 异常 - {e}")
    
    # 测试 2: 测试 QuickTradeService（需要数据库）
    print("\n\n📊 测试 2: QuickTradeService._get_current_price()")
    print("-" * 80)
    try:
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            service = QuickTradeService(session)
            
            for symbol in test_symbols:
                try:
                    price = await service._get_current_price(symbol)
                    if price > 0 and price != 100.0:
                        print(f"✅ {symbol:8} : ${price:10.2f}  (成功)")
                    elif price == 100.0:
                        print(f"⚠️  {symbol:8} : ${price:10.2f}  (默认值)")
                    else:
                        print(f"❌ {symbol:8} : ${price:10.2f}  (失败)")
                except Exception as e:
                    print(f"❌ {symbol:8} : 异常 - {e}")
                    
    except Exception as e:
        print(f"❌ QuickTradeService 测试失败: {e}")
    
    # 总结修复内容
    print("\n\n" + "=" * 80)
    print("📝 修复内容总结")
    print("=" * 80)
    print("\n🔧 问题:")
    print("   - QuickTradeService 调用 market_data.get_price(symbol)")
    print("   - 但 MarketDataProvider 的方法名是 get_current_price(symbol)")
    print("   - 方法名不匹配导致调用失败，返回默认值 100.0")
    
    print("\n✅ 修复:")
    print("   - 将 market_data.get_price() 改为 market_data.get_current_price()")
    print("   - 添加详细日志输出便于调试")
    print("   - 改进异常处理逻辑")
    
    print("\n💡 后续步骤:")
    print("   1. 重启后端服务")
    print("   2. 清除价格缓存（60秒后自动过期）")
    print("   3. 重新调用快捷交易预览接口")
    print("   4. 检查日志输出确认价格获取成功")
    
    print("\n⚙️  注意事项:")
    print("   - 确认 Tiger API 已正确配置（TIGER_PRIVATE_KEY_PATH, TIGER_ID）")
    print("   - 如果 Tiger API 失败，会自动回退到 Yahoo Finance")
    print("   - 价格缓存 60 秒，频繁调用会返回缓存值")
    print("   - 如果所有 API 都失败，会返回默认值 100.0")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(test_price_fix())
