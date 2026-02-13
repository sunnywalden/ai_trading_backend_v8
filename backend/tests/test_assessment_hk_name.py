#!/usr/bin/env python3
"""测试持仓评估API返回的港股名称"""
import asyncio
import httpx
from app.broker.factory import make_option_broker_client


async def test_assessment_hk_names():
    """测试持仓评估API中的港股名称显示"""
    print("=== 测试持仓评估API的港股名称显示 ===\n")
    
    # 方法1: 直接测试底层client
    print("1. 测试底层 Tiger Client 获取的持仓名称:")
    print("-" * 60)
    
    client = make_option_broker_client()
    account_id = await client.get_account_id()
    positions = await client.list_underlying_positions(account_id)
    
    hk_positions = [p for p in positions if p.market == "HK"]
    
    if hk_positions:
        for pos in hk_positions:
            print(f"  {pos.symbol:10} | {pos.name or '(无名称)'}")
    else:
        print("  未找到港股持仓")
    
    print("\n2. 测试持仓评估API返回的名称:")
    print("-" * 60)
    
    # 方法2: 调用实际的API端点
    base_url = "http://localhost:8088"
    
    try:
        async with httpx.AsyncClient() as http_client:
            # 调用持仓评估API
            response = await http_client.get(
                f"{base_url}/api/v1/positions/assessment",
                params={"force_refresh": True},
                timeout=60.0
            )
            
            if response.status_code == 200:
                data = response.json()
                positions_data = data.get("positions", [])
                
                if positions_data:
                    print(f"  找到 {len(positions_data)} 个持仓\n")
                    for pos in positions_data:
                        symbol = pos.get("symbol", "")
                        # 判断是否为港股（港股代码通常是数字）
                        if symbol.isdigit():
                            print(f"  港股: {symbol}")
                            print(f"    - 显示名称: {symbol}")
                            print(f"    - 数量: {pos.get('quantity')}")
                            print(f"    - 现价: {pos.get('current_price')}")
                            print()
                else:
                    print("  未找到任何持仓")
            else:
                print(f"  API调用失败: HTTP {response.status_code}")
                print(f"  响应: {response.text}")
                
    except httpx.ConnectError:
        print("  ✗ 无法连接到服务器")
        print("  请确保服务已启动: uvicorn app.main:app --host 0.0.0.0 --port 8088")
    except Exception as e:
        print(f"  ✗ API调用失败: {e}")
    
    print("\n" + "=" * 60)
    print("提示:")
    print("1. 如果看到港股名称仍是英文，请运行: python clear_hk_name_cache.py")
    print("2. 清除缓存后，再次调用 API 将从 Tiger 获取最新的中文名称")
    print("3. 中文名称会自动缓存30天")


if __name__ == "__main__":
    asyncio.run(test_assessment_hk_names())
