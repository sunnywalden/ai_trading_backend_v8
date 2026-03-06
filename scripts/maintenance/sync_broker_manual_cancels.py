"""将券商侧手动撤单状态回写到本地数据库。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    print(f"orphan_signals_fixed={result.get('orphan_signals_fixed', 0)}")
    print(f"journal_entries_created={result.get('journal_entries_created', 0)}")
    print(f"remaining_EXECUTING={result['remaining_EXECUTING']}")
    print(f"signals_with_order_id={result['signals_with_order_id']}")
    print(f"audit_revoked_marked={result['audit_revoked_marked']}")


if __name__ == "__main__":
    asyncio.run(main())
