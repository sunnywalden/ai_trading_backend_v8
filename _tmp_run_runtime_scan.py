from __future__ import annotations

import asyncio
import json

from app.engine.quant_trading_loop import QuantTradingLoop
from app.models.db import SessionLocal

ACCOUNT_ID = "21272246230273657"


async def main() -> None:
    async with SessionLocal() as session:
        loop = QuantTradingLoop(session)
        result = await loop._trigger_runtime_strategy_scan(ACCOUNT_ID)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
