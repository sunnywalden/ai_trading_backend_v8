"""测试 Tiger API 返回的 assets 数据结构"""
from tigeropen.common.consts import Language, Market
from tigeropen.tiger_open_config import TigerOpenClientConfig
from tigeropen.trade.trade_client import TradeClient
from app.core.config import settings
import json

# 配置
config = TigerOpenClientConfig(sandbox_debug=False)
config.private_key = open(settings.TIGER_PRIVATE_KEY_PATH).read()
config.tiger_id = settings.TIGER_ID
config.account = settings.TIGER_ACCOUNT
config.language = Language.zh_CN

# 创建交易客户端
trade_client = TradeClient(config)

print(f"Getting assets for account: {settings.TIGER_ACCOUNT}")
assets = trade_client.get_assets(account=settings.TIGER_ACCOUNT)

print(f"\nAssets type: {type(assets)}")
print(f"Assets value: {assets}")

if isinstance(assets, list):
    print(f"\nAssets is a list with {len(assets)} items")
    for i, asset in enumerate(assets):
        print(f"\n--- Asset {i} ---")
        print(f"Type: {type(asset)}")
        print(f"Dir: {[x for x in dir(asset) if not x.startswith('_')]}")
        
        # 尝试访问常见属性
        for attr in ['summary', 'net_liquidation', 'equity_with_loan', 'total_cash_balance', 
                     'account', 'category', 'capability', 'currency', 'segments']:
            if hasattr(asset, attr):
                value = getattr(asset, attr)
                print(f"{attr}: {value} (type: {type(value)})")
else:
    print(f"\nAttributes: {[x for x in dir(assets) if not x.startswith('_')]}")
