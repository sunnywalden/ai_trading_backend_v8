#!/usr/bin/env python3
"""测试港股名称缓存功能"""
import asyncio
from app.broker.factory import make_option_broker_client
from app.core.cache import cache

async def test_hk_stock_name_cache():
    """测试港股名称缓存"""
    
    print("=== 测试港股名称缓存功能 ===\n")
    
    # 1. 清除测试缓存（可选）
    print("1. 清除可能存在的测试缓存...")
    test_symbols = ["02513", "00700", "09988"]
    for symbol in test_symbols:
        await cache.delete(f"hk_stock_name:{symbol}")
    print("   缓存已清除\n")
    
    # 2. 第一次获取持仓（从API获取名称）
    print("2. 第一次获取持仓（应该从 Tiger API 获取股票名称）...")
    client = make_option_broker_client()
    account_id = await client.get_account_id()
    
    import time
    start_time = time.time()
    positions = await client.list_underlying_positions(account_id)
    first_time = time.time() - start_time
    
    hk_positions = [p for p in positions if p.market == "HK"]
    print(f"   耗时: {first_time:.3f} 秒")
    print(f"   获取到 {len(hk_positions)} 个港股持仓\n")
    
    if hk_positions:
        for pos in hk_positions:
            print(f"   {pos.symbol} -> {pos.name}")
        print()
    
    # 3. 第二次获取持仓（从缓存获取名称）
    print("3. 第二次获取持仓（应该从缓存获取股票名称）...")
    start_time = time.time()
    positions2 = await client.list_underlying_positions(account_id)
    second_time = time.time() - start_time
    
    hk_positions2 = [p for p in positions2 if p.market == "HK"]
    print(f"   耗时: {second_time:.3f} 秒")
    print(f"   获取到 {len(hk_positions2)} 个港股持仓\n")
    
    if hk_positions2:
        for pos in hk_positions2:
            print(f"   {pos.symbol} -> {pos.name}")
        print()
    
    # 4. 比较性能
    if first_time > 0 and second_time > 0:
        speedup = first_time / second_time
        print(f"4. 性能对比:")
        print(f"   第一次（API调用）: {first_time:.3f} 秒")
        print(f"   第二次（缓存）: {second_time:.3f} 秒")
        print(f"   加速倍数: {speedup:.2f}x")
        print(f"   节省时间: {(first_time - second_time)*1000:.0f} 毫秒\n")
    
    # 5. 检查缓存内容
    print("5. 检查缓存内容:")
    if hk_positions:
        for pos in hk_positions:
            cache_key = f"hk_stock_name:{pos.symbol}"
            cached_name = await cache.get(cache_key)
            status = "✓" if cached_name else "✗"
            print(f"   {status} {cache_key} = {cached_name}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    asyncio.run(test_hk_stock_name_cache())
