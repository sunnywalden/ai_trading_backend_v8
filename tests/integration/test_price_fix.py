#!/usr/bin/env python3
"""测试价格获取功能"""
import asyncio

import pytest

from app.providers.market_data_provider import MarketDataProvider
from tests.external_calls import external_calls_enabled, require_external_calls

pytestmark = pytest.mark.skipif(
    not external_calls_enabled(),
    reason="opt-in market-data call; set RUN_EXTERNAL_INTEGRATION=1",
)

async def test_price_fetching():
    """测试获取 META 价格"""
    require_external_calls()
    provider = MarketDataProvider()
    
    print("🧪 测试价格获取功能...")
    print("=" * 60)
    
    # 测试 META 价格
    symbol = "META"
    print(f"\n📊 获取 {symbol} 当前价格...")
    
    try:
        price = await provider.get_current_price(symbol)
        print(f"✅ {symbol} 当前价格: ${price:.2f}")
        
        if price > 0 and price != 100.0:
            print(f"✅ 价格获取成功（非默认值）")
        elif price == 100.0:
            print(f"⚠️  返回默认值 100.0，可能是API调用失败")
        else:
            print(f"❌ 价格为 0，API调用失败")
            
    except Exception as e:
        print(f"❌ 获取价格失败: {e}")
    
    print("\n" + "=" * 60)
    print("\n📝 修复内容:")
    print("1. 将 market_data.get_price() 修改为 market_data.get_current_price()")
    print("2. MarketDataProvider 使用 Tiger API 优先，Yahoo Finance 备用")
    print("3. 价格缓存 60 秒，减少 API 调用")
    
    print("\n💡 如果仍显示默认值 100.0，检查:")
    print("   - Tiger API 配置是否正确（TIGER_PRIVATE_KEY_PATH, TIGER_ID）")
    print("   - 网络连接是否正常")
    print("   - symbol 格式是否正确")

if __name__ == "__main__":
    require_external_calls()
    asyncio.run(test_price_fetching())
