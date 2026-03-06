from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.models.db import SessionLocal
from app.services.earnings_fence_service import EarningsFenceService
from app.models.event_calendar import EventCalendarEntry, EventType, EventRiskLevel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_earnings_fence():
    print("--- Testing EarningsFenceService ---")
    fence_svc = EarningsFenceService()
    
    # SYSTEM DATE IS Feb 27, 2026
    # Create an event tomorrow (Feb 28, 2026) for TEST_TICKER
    test_symbol = "TEST_TICKER"
    event_date = datetime(2026, 2, 28, 16, 0, 0, tzinfo=timezone.utc)
    
    async with SessionLocal() as db:
        # 1. Clean up old test data
        await db.execute(text(f"DELETE FROM event_calendar_entries WHERE symbol='{test_symbol}'"))
        await db.commit()
        
        # 2. Check fence before (should be inactive)
        status_before = await fence_svc.get_fence_status(db, test_symbol)
        print(f"Status Before (Expected Inactive): active={status_before.active}")
        
        # 3. Add an upcoming earnings event
        entry = EventCalendarEntry(
            symbol=test_symbol,
            event_type=EventType.EARNINGS,
            event_date=event_date,
            title=f"{test_symbol} Test Earnings",
            risk_level=EventRiskLevel.HIGH,
            requires_fence=True,
            source="manual_test"
        )
        db.add(entry)
        await db.commit()
        print(f"Added test event for {test_symbol} on {event_date}")
        
        # 4. Check fence after (should be ACTIVE)
        status_after = await fence_svc.get_fence_status(db, test_symbol)
        print(f"Status After (Expected ACTIVE): active={status_after.active}, reason={status_after.reason}")
        
        if status_after.active:
            print(f"Max Size Pct: {status_after.max_size_pct}")
            
            # 5. Apply fence
            await fence_svc.apply_fence(db, test_symbol)
            
            # Verify applied flag
            stmt = text(f"SELECT fence_applied FROM event_calendar_entries WHERE id={status_after.event_id}")
            result = await db.execute(stmt)
            applied = result.scalar()
            print(f"Fence Applied in DB: {applied}")

if __name__ == "__main__":
    asyncio.run(test_earnings_fence())
