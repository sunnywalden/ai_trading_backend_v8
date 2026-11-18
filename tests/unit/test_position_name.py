#!/usr/bin/env python3
"""Manual Tiger position-attribute inspection.

Importing this file does nothing. Running it can call the broker, so it stays
behind RUN_EXTERNAL_INTEGRATION=1.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from tests.external_calls import require_external_calls

    require_external_calls()

    private_key = os.environ.get("TIGER_PRIVATE_KEY_PATH")
    tiger_id = os.environ.get("TIGER_ID")
    account = os.environ.get("TIGER_ACCOUNT")
    if not all([private_key, tiger_id, account]):
        print(
            "TIGER_PRIVATE_KEY_PATH, TIGER_ID, and TIGER_ACCOUNT must be set "
            "in the environment"
        )
        return 1

    from tigeropen.common.consts import Market, SecurityType
    from tigeropen.tiger_open_config import get_client_config
    from tigeropen.trade.trade_client import TradeClient

    config = get_client_config(
        private_key_path=private_key,
        tiger_id=tiger_id,
        account=account,
    )
    client = TradeClient(config)
    positions = client.get_positions(sec_type=SecurityType.STK, market=Market.HK)
    print(f"HK position count: {len(positions or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
