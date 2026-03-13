from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.providers.market_data_provider import MarketDataProvider

SYMBOLS = ["00700", "01528", "AAPL", "MSFT", "NVDA", "SPY"]


async def main() -> None:
    provider = MarketDataProvider()
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=166)
    lookback_days = 20

    for symbol in SYMBOLS:
        prices = await provider.get_historical_prices(symbol, start_date, end_date)
        current_price = await provider.get_latest_price(symbol)
        print({
            "symbol": symbol,
            "prices_len": len(prices),
            "latest_price": current_price,
            "latest_close": prices[-1]["close"] if prices else None,
            "lookback_high": max((p["high"] for p in prices[-lookback_days:-1]), default=None) if len(prices) >= lookback_days else None,
            "lookback_avg_volume": (sum(p["volume"] for p in prices[-lookback_days:-1]) / max(1, lookback_days - 1)) if len(prices) >= lookback_days else None,
        })
        try:
            stats = await provider.get_key_statistics(symbol)
            print({
                "symbol": symbol,
                "stats_ok": True,
                "roe": stats.get("roe"),
                "debt_to_equity": stats.get("debt_to_equity"),
                "free_cash_flow": stats.get("free_cash_flow"),
            })
        except Exception as exc:
            print({"symbol": symbol, "stats_ok": False, "error": str(exc)[:160]})


if __name__ == "__main__":
    asyncio.run(main())
