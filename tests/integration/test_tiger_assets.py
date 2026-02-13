#!/usr/bin/env python3
"""测试 Tiger API 返回的 assets 数据结构

说明：该脚本现在位于 `tests/integration/`（可在部署/CI 中直接运行）。
"""

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings

from tigeropen.common.consts import Language
from tigeropen.tiger_open_config import TigerOpenClientConfig
from tigeropen.trade.trade_client import TradeClient


def main() -> None:
    if not settings.TIGER_PRIVATE_KEY_PATH or not settings.TIGER_ID:
        raise SystemExit("TIGER_PRIVATE_KEY_PATH / TIGER_ID 未配置，无法测试 assets")

    config = TigerOpenClientConfig(sandbox_debug=False)
    config.private_key = Path(settings.TIGER_PRIVATE_KEY_PATH).read_text(encoding="utf-8")
    config.tiger_id = settings.TIGER_ID
    config.account = settings.TIGER_ACCOUNT
    config.language = Language.zh_CN

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

            for attr in [
                "summary",
                "net_liquidation",
                "equity_with_loan",
                "total_cash_balance",
                "account",
                "category",
                "capability",
                "currency",
                "segments",
            ]:
                if hasattr(asset, attr):
                    value = getattr(asset, attr)
                    print(f"{attr}: {value} (type: {type(value)})")
    else:
        print(f"\nAttributes: {[x for x in dir(assets) if not x.startswith('_')]}")

    # 额外输出 JSON（若对象可序列化）
    try:
        print("\nJSON dump preview:")
        print(json.dumps(assets, ensure_ascii=False, default=str)[:2000])
    except Exception:
        pass


if __name__ == "__main__":
    main()
