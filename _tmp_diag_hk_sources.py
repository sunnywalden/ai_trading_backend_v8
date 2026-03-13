import asyncio
from app.providers.market_data_provider import MarketDataProvider

SYMBOLS = ["00700", "09988", "03690", "01810", "09618"]


async def main() -> None:
    md = MarketDataProvider()
    print("HK SOURCE DIAG")
    for sym in SYMBOLS:
        tiger_sym = md._to_tiger_symbol(sym)
        yahoo_sym = md._to_yahoo_symbol(sym)
        try:
            tiger_price = await md._get_tiger_price_single(sym)
        except Exception as exc:
            tiger_price = f"ERR:{exc}"
        try:
            tiger_bars = await md._get_tiger_bars(sym, "1y")
            tiger_bars_len = 0 if tiger_bars is None else len(tiger_bars)
        except Exception as exc:
            tiger_bars_len = f"ERR:{exc}"
        try:
            yahoo_bars = await md._get_yahoo_data_with_retry(sym, "1y", "1d")
            yahoo_bars_len = 0 if yahoo_bars is None else len(yahoo_bars)
        except Exception as exc:
            yahoo_bars_len = f"ERR:{exc}"
        print({
            "symbol": sym,
            "tiger_sym": tiger_sym,
            "yahoo_sym": yahoo_sym,
            "tiger_price": tiger_price,
            "tiger_bars_len": tiger_bars_len,
            "yahoo_bars_len": yahoo_bars_len,
        })


if __name__ == "__main__":
    asyncio.run(main())
