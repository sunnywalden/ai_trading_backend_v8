from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import json

from app.models.db import SessionLocal
from app.services.broker_order_sync_service import reconcile_broker_order_status


async def main() -> None:
    async with SessionLocal() as db:
        result = await reconcile_broker_order_status(db)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
