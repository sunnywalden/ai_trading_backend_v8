"""将券商侧手动撤单状态回写到本地数据库。"""
import asyncio

from app.models.db import SessionLocal
from app.services.broker_order_sync_service import reconcile_broker_order_status


async def main() -> None:
    async with SessionLocal() as session:
        result = await reconcile_broker_order_status(session=session, lookback_days=3)

    print("--- sync summary ---")
    print(f"account_id={result['account_id']}")
    print(f"candidate_order_ids={result['candidate_order_ids']}")
    print(f"sync_executing.signals={result['sync_executing']['signals']}")
    print(f"sync_executing.updates={result['sync_executing']['updates']}")
    print(f"cancelled_synced={result['cancelled_synced']}")
    print(f"filled_synced={result['filled_synced']}")
    print(f"remaining_EXECUTING={result['remaining_EXECUTING']}")
    print(f"signals_with_order_id={result['signals_with_order_id']}")
    print(f"audit_revoked_marked={result['audit_revoked_marked']}")


if __name__ == "__main__":
    asyncio.run(main())
