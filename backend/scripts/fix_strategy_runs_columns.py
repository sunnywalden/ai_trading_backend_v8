import asyncio
import os
import sys

# Ensure the parent directory is in sys.path so 'app' can be found
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from app.models.db import engine
from app.core.config import settings

async def migrate():
    print(f"Applying schema changes to {settings.DB_TYPE}...")
    
    async with engine.begin() as conn:
        if settings.DB_TYPE == "mysql":
            # MySQL / MariaDB syntax
            try:
                print("Adding columns: min_score, max_results, priority...")
                await conn.execute(text("ALTER TABLE strategy_runs ADD COLUMN min_score INT"))
                await conn.execute(text("ALTER TABLE strategy_runs ADD COLUMN max_results INT"))
                await conn.execute(text("ALTER TABLE strategy_runs ADD COLUMN priority INT"))
                print("Columns added successfully.")
            except Exception as e:
                print(f"Skipped adding columns (they might already exist): {e}")

            try:
                print("Dropping columns: budget, param_snapshot...")
                await conn.execute(text("ALTER TABLE strategy_runs DROP COLUMN budget"))
                await conn.execute(text("ALTER TABLE strategy_runs DROP COLUMN param_snapshot"))
                print("Columns dropped successfully.")
            except Exception as e:
                print(f"Skipped dropping columns: {e}")
        
        else:
            # SQLite syntax
            try:
                print("Adding columns to SQLite...")
                await conn.execute(text("ALTER TABLE strategy_runs ADD COLUMN min_score INTEGER"))
                await conn.execute(text("ALTER TABLE strategy_runs ADD COLUMN max_results INTEGER"))
                await conn.execute(text("ALTER TABLE strategy_runs ADD COLUMN priority INTEGER"))
                print("Columns added successfully.")
            except Exception as e:
                print(f"Skipped adding columns: {e}")
                
            # SQLite doesn't support DROP COLUMN in older versions easily, 
            # and it's generally safe to leave them or we'd have to recreate the table.
            # Leaving them for now as it's just SQLite.

    await engine.dispose()
    print("✅ Migration completed.")

if __name__ == "__main__":
    asyncio.run(migrate())
