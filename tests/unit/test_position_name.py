#!/usr/bin/env python3
"""测试Tiger API position对象的属性"""
from tigeropen.tiger_open_config import get_client_config
from tigeropen.trade.trade_client import TradeClient
from tigeropen.common.consts import SecurityType, Market
import os
import sys

# 直接从环境变量获取
private_key = os.environ.get('TIGER_PRIVATE_KEY_PATH')
tiger_id = os.environ.get('TIGER_ID')
account = os.environ.get('TIGER_ACCOUNT')

if not all([private_key, tiger_id, account]):
    print("Please set environment variables: TIGER_PRIVATE_KEY_PATH, TIGER_ID, TIGER_ACCOUNT")
    sys.exit(1)

if private_key and tiger_id and account:
    config = get_client_config(private_key_path=private_key, tiger_id=tiger_id, account=account)
    client = TradeClient(config)
    
    positions = client.get_positions(sec_type=SecurityType.STK, market=Market.HK)
    
    if positions and len(positions) > 0:
        print(f"Found {len(positions)} HK positions\n")
        
        for i, pos in enumerate(positions):
            print(f"=== Position {i+1} ===")
            print(f"Position attributes: {[attr for attr in dir(pos) if not attr.startswith('_')]}")
            
            if hasattr(pos, 'contract'):
                print(f"\nContract attributes: {[attr for attr in dir(pos.contract) if not attr.startswith('_')]}")
                
                # 检查常见的名称字段
                for name_field in ['name', 'local_symbol', 'symbol', 'sec_name', 'stock_name']:
                    if hasattr(pos.contract, name_field):
                        value = getattr(pos.contract, name_field)
                        print(f"  {name_field}: {value}")
                
            print()
    else:
        print('No HK positions found')
else:
    print('Tiger config not found in environment variables')
