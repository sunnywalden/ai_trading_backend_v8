import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.config import settings
from sqlalchemy import create_engine, text

def migrate():
    # Construct database URL
    db_url = f"mysql+pymysql://{settings.DATABASE_USER}:{settings.DATABASE_PASSWORD}@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        print("Adding 'action' and 'direction' columns to strategy_run_assets...")
        try:
            conn.execute(text("ALTER TABLE strategy_run_assets ADD COLUMN action VARCHAR(16) AFTER weight;"))
            conn.execute(text("ALTER TABLE strategy_run_assets ADD COLUMN direction VARCHAR(16) AFTER action;"))
            conn.commit()
            print("Successfully added columns.")
        except Exception as e:
            print(f"Error adding columns: {e}")

if __name__ == "__main__":
    migrate()
