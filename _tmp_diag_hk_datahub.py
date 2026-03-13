import asyncio
from datetime import date, timedelta
from app.data.hub import DataHub

SYMBOLS = ["00700", "09988", "03690", "01810", "09618"]


async def main() -> None:
    hub = DataHub()
    start = date.today() - timedelta(days=365)
    end = date.today()
    print("HK DATAHUB DIAG")
    for sym in SYMBOLS:
        try:
            df = await hub.get_ohlcv(sym, start=start, end=end, interval="1d")
            print({"symbol": sym, "rows": 0 if df is None else len(df)})
        except Exception as exc:
            print({"symbol": sym, "error": str(exc)})


if __name__ == "__main__":
    asyncio.run(main())
