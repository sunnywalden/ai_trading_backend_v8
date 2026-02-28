import asyncio
import os, sys
sys.path.append(os.getcwd())

import app.models.strategy
from app.models.db import SessionLocal
from app.models.trading_signal import TradingSignal, SignalStatus
from app.models.autonomy_audit_log import AutonomyAuditLog
from sqlalchemy import select, and_

async def check():
    async with SessionLocal() as s:
        r = await s.execute(select(TradingSignal).where(
            and_(TradingSignal.symbol.in_(["CRM", "AMD", "AMZN"]),
                 TradingSignal.status == SignalStatus.EXECUTED)
        ).limit(10))
        print("=== EXECUTED signals for CRM/AMD/AMZN ===")
        for sig in r.scalars().all():
            print(f"  {sig.symbol} | order_id={sig.order_id} | created={sig.created_at}")

        r2 = await s.execute(
            select(AutonomyAuditLog.symbol)
            .where(AutonomyAuditLog.revoked_at.is_not(None))
            .distinct()
        )
        print("=== Revoked audit symbols ===")
        print([row[0] for row in r2.all()])

if __name__ == "__main__":
    asyncio.run(check())
