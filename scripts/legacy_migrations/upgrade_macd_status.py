"""Upgrade script: extend `macd_status` column length to avoid "Data too long" errors.

Usage:
    ./venv/bin/python scripts/upgrade_macd_status.py

This script is safe to run multiple times; it will check current length and only ALTER when needed.
"""
import asyncio
import os
import sys

# Ensure the parent directory is in sys.path so 'app' can be found
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from app.models.db import engine
from app.core.config import settings

TARGET_LENGTH = 64

async def main():
    print("Checking `position_trend_snapshots.macd_status` column...")

    async with engine.begin() as conn:
        if settings.DB_TYPE == "mysql":
            res = await conn.execute(text(
                "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'position_trend_snapshots' "
                "AND column_name = 'macd_status'"
            ))
            row = res.first()
            cur_len = row[0] if row else None

            if cur_len is None:
                print("Could not find column information; verify the table exists.")
                return

            print(f"Current max length: {cur_len}")

            if cur_len >= TARGET_LENGTH:
                print("No action needed; length is already sufficient.")
                return

            alter_sql = f"ALTER TABLE position_trend_snapshots MODIFY COLUMN macd_status VARCHAR({TARGET_LENGTH})"
            print(f"Altering column to VARCHAR({TARGET_LENGTH})...")
            await conn.execute(text(alter_sql))
            print("✅ Alteration complete.")

        else:
            # SQLite doesn't enforce VARCHAR length; other DBs may require manual migration
            print("Non-MySQL DB detected; SQLite typically ignores VARCHAR length. If using another DB, apply an appropriate ALTER statement manually.")


if __name__ == "__main__":
    asyncio.run(main())
