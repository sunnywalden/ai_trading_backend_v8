from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
from sqlalchemy import text
from app.models.db import engine

async def main():
    async with engine.connect() as conn:
        print("--- Table: copilot_messages ---")
        res = await conn.execute(text("DESCRIBE copilot_messages"))
        for row in res.fetchall():
            print(row)

if __name__ == "__main__":
    asyncio.run(main())
