import asyncio
from sqlalchemy import text
from app.models.db import SessionLocal
async def main():
    async with SessionLocal() as db:
        res = await db.execute(text("SELECT COUNT(*) FROM trading_signals WHERE status='VALIDATED' AND symbol NOT LIKE '%.SZ' AND symbol NOT LIKE '%.SH'"))
        print("Validated non-A signals:", res.scalar())
        res2 = await db.execute(text("SELECT DATE(created_at) as d, user_id, account_id, COUNT(*) FROM trading_signals WHERE status='VALIDATED' AND symbol NOT LIKE '%.SZ' AND symbol NOT LIKE '%.SH' GROUP BY DATE(created_at), user_id, account_id ORDER BY DATE(created_at) DESC LIMIT 10"))
        print("Distribution:\n", "\n".join([str(r) for r in res2.all()]))
asyncio.run(main())
