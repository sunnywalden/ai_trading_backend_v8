from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from app.data.hub import data_hub
from app.providers.market_data_provider import market_data_provider

SYMBOLS = ["00700", "AAPL", "MSFT", "SPY"]


async def main() -> None:
    for symbol in SYMBOLS:
        try:
            bars = await market_data_provider._get_tiger_bars(symbol, "6mo")
            print({"path": "provider_tiger_bars", "symbol": symbol, "rows": 0 if bars is None else len(bars), "cols": [] if bars is None else list(bars.columns)[:6]})
        except Exception as exc:
            print({"path": "provider_tiger_bars", "symbol": symbol, "error": str(exc)[:200]})

        try:
            df = await data_hub._tiger_ohlcv(symbol, date.today() - timedelta(days=180), date.today(), "1d")
            print({"path": "datahub_tiger_ohlcv", "symbol": symbol, "rows": 0 if df is None else len(df), "cols": [] if df is None else list(df.columns)[:6]})
        except Exception as exc:
            print({"path": "datahub_tiger_ohlcv", "symbol": symbol, "error": str(exc)[:200]})


if __name__ == "__main__":
    asyncio.run(main())
