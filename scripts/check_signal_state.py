import asyncio
import os, sys
sys.path.append(os.getcwd())

import app.models.strategy
from app.models.db import SessionLocal, close_db_resources
from app.models.trading_signal import TradingSignal, SignalStatus
from app.models.autonomy_audit_log import AutonomyAuditLog
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, and_

TODAY_UTC = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
YESTERDAY_UTC = TODAY_UTC - timedelta(days=1)

async def check():
    async with SessionLocal() as s:
        account_id_row = await s.execute(select(TradingSignal.account_id).limit(1))
        account_id = account_id_row.scalar()
        print(f"account_id: {account_id}\n")

        # 1. 今日交易次数（和 /status API 计算逻辑一致）
        r1 = await s.execute(select(func.count(TradingSignal.id)).where(and_(
            TradingSignal.account_id == account_id,
            TradingSignal.status == SignalStatus.EXECUTED,
            TradingSignal.executed_at >= TODAY_UTC,
        )))
        daily_trades = r1.scalar() or 0
        print(f"=== 今日交易次数 (executed_at >= today) = {daily_trades} ===")

        # 2. 今日实际发起过的订单（含已撤销）
        r2 = await s.execute(select(func.count(AutonomyAuditLog.id)).where(and_(
            AutonomyAuditLog.account_id == account_id,
            AutonomyAuditLog.order_id.is_not(None),
            AutonomyAuditLog.created_at >= TODAY_UTC,
        )))
        broker_orders_today = r2.scalar() or 0
        print(f"=== 今日实际下单数 (audit_log with order_id) = {broker_orders_today} ===")

        # 3. 信号流水线（和 /status API 计算逻辑一致，last 24h）
        r3 = await s.execute(
            select(TradingSignal.status, func.count(TradingSignal.id))
            .where(and_(
                TradingSignal.account_id == account_id,
                TradingSignal.created_at >= YESTERDAY_UTC,
            ))
            .group_by(TradingSignal.status)
        )
        print("\n=== 信号流水线 (last 24h created_at) ===")
        pipeline = {}
        for row in r3.fetchall():
            k = row[0].value if hasattr(row[0], "value") else str(row[0])
            pipeline[k] = row[1]
            print(f"  {k}: {row[1]}")

        # 4. 审计日志中今日已撤销的订单
        r4 = await s.execute(select(func.count(AutonomyAuditLog.id)).where(and_(
            AutonomyAuditLog.account_id == account_id,
            AutonomyAuditLog.revoked_at.is_not(None),
            AutonomyAuditLog.created_at >= TODAY_UTC,
        )))
        revoked_today = r4.scalar() or 0
        print(f"\n=== 今日审计日志-撤销数 = {revoked_today} ===")

        # 5. 今日创建的信号明细（关键列）
        r5 = await s.execute(
            select(TradingSignal.symbol, TradingSignal.status, TradingSignal.order_id, TradingSignal.executed_at)
            .where(and_(
                TradingSignal.account_id == account_id,
                TradingSignal.created_at >= TODAY_UTC,
            ))
            .order_by(TradingSignal.created_at.desc())
        )
        print("\n=== 今日信号明细 ===")
        print(f"{'Symbol':<8} {'Status':<12} {'order_id':<25} {'executed_at'}")
        for row in r5.fetchall():
            oid = (row[2] or "")[:22]
            print(f"  {row[0]:<8} {str(row[1].value if hasattr(row[1],'value') else row[1]):<12} {oid:<25} {row[3]}")


async def main():
    try:
        await check()
    finally:
        await close_db_resources()

if __name__ == "__main__":
    asyncio.run(main())
