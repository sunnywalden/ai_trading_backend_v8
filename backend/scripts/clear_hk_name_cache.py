#!/usr/bin/env python3
"""清除港股名称缓存

由于港股名称从英文改为优先显示中文，需要清除旧的缓存数据。
运行此脚本将清除所有 hk_stock_name:* 缓存。
"""
import asyncio
from app.core.cache import cache


async def clear_hk_name_cache():
    """清除所有港股名称缓存"""
    print("=== 清除港股名称缓存 ===\n")
    
    # 这里列出可能的港股symbol
    # 如果您知道具体的持仓symbol，可以在这里添加
    # 例如: ["02513", "00700", "09988", "01810"]
    known_symbols = [
        "02513",  # 智谱
        "00700",  # 腾讯
        "09988",  # 阿里巴巴
        "01810",  # 小米
    ]
    
    print(f"正在清除 {len(known_symbols)} 个已知港股symbol的缓存...")
    for symbol in known_symbols:
        cache_key = f"hk_stock_name:{symbol}"
        try:
            await cache.delete(cache_key)
            print(f"  已清除: {cache_key}")
        except Exception as e:
            print(f"  清除失败 {cache_key}: {e}")
    
    print("\n✓ 缓存清除完成")
    print("\n提示：")
    print("1. 下次调用 /api/v1/positions/assessment 时，系统会重新从 Tiger API 获取港股中文名称")
    print("2. 新的名称会自动缓存30天")
    print("3. 如果您的持仓包含其他港股，请在上面的 known_symbols 列表中添加")


if __name__ == "__main__":
    asyncio.run(clear_hk_name_cache())
