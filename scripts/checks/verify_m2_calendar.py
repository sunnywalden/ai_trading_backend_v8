from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Mock the settings or use existing config
try:
    from app.core.config import settings
    from app.services.event_calendar_service import event_calendar_service
    from app.models.db import SessionLocal
except ImportError:
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
    from app.core.config import settings
    from app.services.event_calendar_service import event_calendar_service
    from app.models.db import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_event_calendar():
    print("--- Testing EventCalendarService ---")
    
    # We use the real DB defined in settings (likely MySQL if .env is active)
    async with SessionLocal() as db:
        test_symbols = ["AAPL", "TSLA", "MSFT"]
        print(f"Scanning for symbols: {test_symbols}")
        
        import yfinance as yf
        for s in test_symbols:
            t = yf.Ticker(s)
            print(f"Raw calendar for {s}: {t.calendar}")

        # Look ahead 90 days to be sure we find something
        new_entries = await event_calendar_service.scan_and_upsert(db, symbols=test_symbols, lookahead_days=90)
        
        print(f"Success! Added {len(new_entries)} new entries.")
        for entry in new_entries:
            print(f" - [{entry.symbol}] {entry.event_type} on {entry.event_date}: {entry.title}")
            
        # Verify query interface
        upcoming = await event_calendar_service.get_upcoming(db, days=30)
        print(f"\nTotal upcoming events in next 30 days: {len(upcoming)}")
        for entry in upcoming[:5]:
            print(f" - {entry.event_date.strftime('%Y-%m-%d')} | {entry.symbol} | {entry.event_type} | {entry.title}")

if __name__ == "__main__":
    asyncio.run(test_event_calendar())
