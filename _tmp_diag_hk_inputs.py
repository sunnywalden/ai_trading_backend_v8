import asyncio
from datetime import datetime, timedelta

from sqlalchemy import text

from app.models.db import SessionLocal
from app.providers.market_data_provider import MarketDataProvider

SYMBOLS = ["00700", "09988", "03690", "01810", "09618"]


async def main() -> None:
    md = MarketDataProvider()
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=200)

    async with SessionLocal() as s:
        print("HK INPUT DIAG")
        for sym in SYMBOLS:
            try:
                prices = await md.get_historical_prices(sym, start_date, end_date)
                last_price = await md.get_latest_price(sym)
                try:
                    stats = await md.get_key_statistics(sym)
                    stats_ok = True
                except Exception as exc:
                    stats = {"error": str(exc)}
                    stats_ok = False

                atr_row = (
                    await s.execute(
                        text(
                            """
                            SELECT symbol, timeframe, timestamp, atr_14, ma_50, ma_200, bb_upper, bb_lower
                            FROM technical_indicators
                            WHERE symbol = :symbol
                            ORDER BY timestamp DESC
                            LIMIT 1
                            """
                        ),
                        {"symbol": sym},
                    )
                ).mappings().first()

                print({
                    "symbol": sym,
                    "prices_len": len(prices),
                    "latest_price": last_price,
                    "stats_ok": stats_ok,
                    "stats_keys": sorted(list(stats.keys()))[:8],
                    "roe": stats.get("roe") if isinstance(stats, dict) else None,
                    "debt_to_equity": stats.get("debt_to_equity") if isinstance(stats, dict) else None,
                    "atr_cache": dict(atr_row) if atr_row else None,
                })
            except Exception as exc:
                print({"symbol": sym, "error": str(exc)})


if __name__ == "__main__":
    asyncio.run(main())
