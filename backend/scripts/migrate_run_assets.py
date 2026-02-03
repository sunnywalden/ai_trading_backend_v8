import asyncio
from sqlalchemy import text
from app.models.db import engine
from app.core.config import settings

async def migrate():
    print(f"Applying schema changes to {settings.DB_TYPE} for strategy_run_assets...")
    
    async with engine.begin() as conn:
        if settings.DB_TYPE == "mysql":
            try:
                print("Adding columns: action, direction to strategy_run_assets...")
                await conn.execute(text("ALTER TABLE strategy_run_assets ADD COLUMN action VARCHAR(16)"))
                await conn.execute(text("ALTER TABLE strategy_run_assets ADD COLUMN direction VARCHAR(16)"))
                print("Columns added successfully.")
            except Exception as e:
                print(f"Skipped adding columns (they might already exist): {e}")
        else:
            try:
                print("Adding columns to SQLite...")
                await conn.execute(text("ALTER TABLE strategy_run_assets ADD COLUMN action TEXT"))
                await conn.execute(text("ALTER TABLE strategy_run_assets ADD COLUMN direction TEXT"))
                print("Columns added successfully.")
            except Exception as e:
                print(f"Skipped adding columns: {e}")

    print("✅ Migration completed.")

if __name__ == "__main__":
    asyncio.run(migrate())
