
import asyncio
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select, delete
from app.models.db import SessionLocal
from app.models.equity_snapshot import EquitySnapshot
from app.core.config import settings

async def init_demo_equity():
    account_id = settings.TIGER_ACCOUNT
    print(f"Initializing demo equity for account: {account_id}")
    
    async with SessionLocal() as session:
        # 清理旧数据
        # await session.execute(delete(EquitySnapshot).where(EquitySnapshot.account_id == account_id))
        
        today = date.today()
        base_equity = 900000.0
        
        for i in range(30, -1, -1):
            target_date = today - timedelta(days=i)
            # 模拟变动
            day_pnl = (hash(str(target_date)) % 20000) - 10000
            current_equity = base_equity + day_pnl + (30-i)*500
            
            # 检查是否已存在
            stmt = select(EquitySnapshot).where(
                EquitySnapshot.account_id == account_id,
                EquitySnapshot.snapshot_date == target_date
            )
            existing = (await session.execute(stmt)).scalars().first()
            
            if not existing:
                snapshot = EquitySnapshot(
                    account_id=account_id,
                    snapshot_date=target_date,
                    total_equity=Decimal(str(current_equity)),
                    cash=Decimal(str(current_equity * 0.2)),
                    market_value=Decimal(str(current_equity * 0.8)),
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal(str(day_pnl)),
                    daily_return=Decimal(str(day_pnl / base_equity)),
                    cumulative_return=Decimal(str((current_equity - 900000.0) / 900000.0))
                )
                session.add(snapshot)
        
        await session.commit()
    print("Demo equity data initialized.")

if __name__ == "__main__":
    asyncio.run(init_demo_equity())
