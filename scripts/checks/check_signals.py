
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
from sqlalchemy import select
from app.models.db import SessionLocal, close_db_resources
from app.models.trading_signal import TradingSignal, SignalStatus
from app.models.strategy import Strategy  # 导入以解决关系映射问题

async def check():
    async with SessionLocal() as session:
        stmt = select(TradingSignal.signal_id, TradingSignal.symbol, TradingSignal.status, TradingSignal.account_id)
        result = await session.execute(stmt)
        signals = result.all()
        print(f"Total signals: {len(signals)}")
        for s in signals:
            print(f"ID: {s.signal_id}, Symbol: {s.symbol}, Status: {s.status}, Account: {s.account_id}")


async def main():
    try:
        await check()
    finally:
        await close_db_resources()

if __name__ == "__main__":
    asyncio.run(main())
