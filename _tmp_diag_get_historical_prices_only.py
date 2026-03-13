from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.providers.market_data_provider import market_data_provider

SYMBOLS = ["AAPL", "MSFT", "SPY", "00700"]


async def main() -> None:
    end_date = datetime.now(UTC).replace(tzinfo=None)
    start_date = end_date - timedelta(days=166)
    for symbol in SYMBOLS:
        prices = await market_data_provider.get_historical_prices(symbol, start_date, end_date)
        print({
            "symbol": symbol,
            "len": len(prices),
            "head": prices[:1],
            "tail": prices[-1:] if prices else [],
        })


if __name__ == "__main__":
    asyncio.run(main())
