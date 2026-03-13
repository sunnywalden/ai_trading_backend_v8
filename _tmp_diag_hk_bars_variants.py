import asyncio
from app.providers.market_data_provider import MarketDataProvider

SYMBOLS = ["09988", "9988", "03690", "3690", "01810", "1810", "09618", "9618", "00700", "700"]


async def main() -> None:
    md = MarketDataProvider()
    print("HK BARS VARIANTS")
    for sym in SYMBOLS:
        try:
            df = await md._get_tiger_bars(sym, "1y")
            print({"symbol": sym, "tiger_sym": md._to_tiger_symbol(sym), "bars_len": 0 if df is None else len(df)})
        except Exception as exc:
            print({"symbol": sym, "tiger_sym": md._to_tiger_symbol(sym), "error": str(exc)})


if __name__ == "__main__":
    asyncio.run(main())
