from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.providers.market_data_provider import market_data_provider

HK_SYMBOLS = ["00700", "09988", "03690", "01810", "09618", "09888", "00005", "02318", "01299", "00941", "01528", "02192"]


async def main() -> None:
    end_date = datetime.now(UTC).replace(tzinfo=None)
    start_date = end_date - timedelta(days=166)
    for symbol in HK_SYMBOLS:
        prices = await market_data_provider.get_historical_prices(symbol, start_date, end_date)
        if len(prices) < 60:
            print({"symbol": symbol, "prices_len": len(prices), "momentum_return": None})
            continue
        latest_close = float(prices[-1]["close"])
        anchor_close = float(prices[max(0, len(prices) - 120)]["close"])
        momentum_return = (latest_close - anchor_close) / anchor_close if anchor_close else None
        print({
            "symbol": symbol,
            "prices_len": len(prices),
            "latest_close": latest_close,
            "anchor_close": anchor_close,
            "momentum_return": momentum_return,
        })


if __name__ == "__main__":
    asyncio.run(main())
