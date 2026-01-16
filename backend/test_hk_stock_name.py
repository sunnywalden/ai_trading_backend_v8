#!/usr/bin/env python3
"""测试港股名称显示功能"""
import asyncio
from app.broker.factory import make_option_broker_client

async def test_hk_stock_names():
    """测试获取港股持仓并显示股票名称"""
    client = make_option_broker_client()
    account_id = await client.get_account_id()
    
    print(f"Account ID: {account_id}")
    print("\n=== Testing HK Stock Name Display ===\n")
    
    # 获取所有股票持仓
    positions = await client.list_underlying_positions(account_id)
    
    if not positions:
        print("No positions found")
        return
    
    print(f"Total positions: {len(positions)}\n")
    
    # 显示港股持仓
    hk_positions = [p for p in positions if p.market == "HK"]
    if hk_positions:
        print("=== HK Stock Positions ===")
        for pos in hk_positions:
            display_name = pos.name if pos.name else pos.symbol
            print(f"  Symbol: {pos.symbol}")
            print(f"  Display Name: {display_name}")
            print(f"  Quantity: {pos.quantity}")
            print(f"  Avg Price: {pos.avg_price}")
            print(f"  Last Price: {pos.last_price}")
            print(f"  Market Value: {pos.quantity * pos.last_price:.2f} {pos.currency}")
            print()
    else:
        print("No HK positions found")
    
    # 显示美股持仓
    us_positions = [p for p in positions if p.market == "US"]
    if us_positions:
        print("\n=== US Stock Positions ===")
        for pos in us_positions:
            print(f"  {pos.symbol}: {pos.quantity} shares @ {pos.last_price}")

if __name__ == "__main__":
    asyncio.run(test_hk_stock_names())
