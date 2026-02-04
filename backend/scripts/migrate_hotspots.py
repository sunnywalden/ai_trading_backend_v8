import asyncio
import os
import sys

# Ensure the parent directory is in sys.path so 'app' can be found
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from sqlalchemy import text
from app.models.db import engine
from app.core.config import settings

async def migrate():
    print(f"Applying schema changes to {settings.DB_TYPE} for market hotspots...")
    
    async with engine.begin() as conn:
        if settings.DB_TYPE == "mysql":
            # Check existing columns
            res = await conn.execute(text("SHOW COLUMNS FROM geopolitical_events"))
            existing_cols = [row[0] for row in res.fetchall()]
            
            # List of columns to check and add
            columns = [
                ("category", "VARCHAR(32)"),
                ("affected_regions", "TEXT"),
                ("affected_industries", "TEXT"),
                ("created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
            ]
            
            for col_name, col_type in columns:
                if col_name not in existing_cols:
                    print(f"Adding column: {col_name}...")
                    await conn.execute(text(f"ALTER TABLE geopolitical_events ADD COLUMN {col_name} {col_type}"))
                else:
                    print(f"Column {col_name} already exists, skipping.")

            # Also ensure 'title' is long enough and 'news_url' is Text
            print("Optimizing column lengths...")
            await conn.execute(text("ALTER TABLE geopolitical_events MODIFY title VARCHAR(200)"))
            await conn.execute(text("ALTER TABLE geopolitical_events MODIFY news_url TEXT"))
        
        else:
            # SQLite
            print("SQLite: creating new table if not exists...")
            from app.models.db import Base
            # Base.metadata.create_all is sync, so we run_sync
            await conn.run_sync(Base.metadata.create_all)

    print("✅ Market hotspots migration completed.")

if __name__ == "__main__":
    asyncio.run(migrate())
