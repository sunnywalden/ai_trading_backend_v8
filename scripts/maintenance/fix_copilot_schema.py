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
        print("--- Fixing copilot_messages schema ---")
        # Increase role column length to 16
        await conn.execute(text("ALTER TABLE copilot_messages MODIFY COLUMN role VARCHAR(16) NOT NULL"))
        print("Done! role column set to VARCHAR(16)")
        await conn.commit()

if __name__ == "__main__":
    asyncio.run(main())
