"""检查手动撤单同步后的关键状态。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio

from sqlalchemy import desc, select

import app.models.strategy  # noqa: F401
from app.broker.factory import make_option_broker_client
from app.models.autonomy_audit_log import AutonomyAuditLog
from app.models.db import SessionLocal
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.trading_signal import TradingSignal


async def main() -> None:
    broker = make_option_broker_client()
    account_id = str(await broker.get_account_id())
    print(f"account_id={account_id}")

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    TradingSignal.id,
                    TradingSignal.symbol,
                    TradingSignal.status,
                    TradingSignal.order_id,
                    TradingSignal.updated_at,
                )
                .where(TradingSignal.account_id == account_id)
                .where(TradingSignal.order_id.is_not(None))
                .order_by(desc(TradingSignal.id))
                .limit(20)
            )
        ).all()
        print("\n=== signals still carrying order_id (top 20) ===")
        for r in rows:
            print(r)

        revoked = (
            await session.execute(
                select(
                    AutonomyAuditLog.id,
                    AutonomyAuditLog.order_id,
                    AutonomyAuditLog.symbol,
                    AutonomyAuditLog.revoked_at,
                    AutonomyAuditLog.revoke_reason,
                )
                .where(AutonomyAuditLog.account_id == account_id)
                .where(AutonomyAuditLog.revoked_at.is_not(None))
                .order_by(desc(AutonomyAuditLog.id))
                .limit(15)
            )
        ).all()
        print("\n=== latest revoked audit logs (top 15) ===")
        for r in revoked:
            print(r)

        intents = (
            await session.execute(
                select(
                    AutonomousExecutionIntent.id,
                    AutonomousExecutionIntent.order_id,
                    AutonomousExecutionIntent.status,
                    AutonomousExecutionIntent.reason,
                    AutonomousExecutionIntent.updated_at,
                )
                .where(AutonomousExecutionIntent.account_id == account_id)
                .order_by(desc(AutonomousExecutionIntent.id))
                .limit(15)
            )
        ).all()
        print("\n=== latest execution intents (top 15) ===")
        for r in intents:
            print(r)


if __name__ == "__main__":
    asyncio.run(main())
