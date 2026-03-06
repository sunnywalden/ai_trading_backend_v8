"""v10.3.2 数据验收检查脚本（只读）。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
from sqlalchemy import text


ACCOUNT_ID = "21272246230273657"


async def main() -> None:
    from app.models.db import engine

    async with engine.connect() as conn:
        print("=== trading_signals 状态分布 ===")
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT status, COUNT(*)
                    FROM trading_signals
                    WHERE account_id = :account_id
                    GROUP BY status
                    ORDER BY status
                    """
                ),
                {"account_id": ACCOUNT_ID},
            )
        ).fetchall()
        for status, cnt in rows:
            print(status, cnt)

        print("\n=== 最近12条 trading_signals ===")
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, symbol, status, quantity_mode, quantity_value, suggested_quantity, created_at
                    FROM trading_signals
                    WHERE account_id = :account_id
                    ORDER BY id DESC
                    LIMIT 12
                    """
                ),
                {"account_id": ACCOUNT_ID},
            )
        ).fetchall()
        for r in rows:
            print(r)

        print("\n=== autonomous_execution_intent 状态分布 ===")
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT status, COUNT(*)
                    FROM autonomous_execution_intent
                    WHERE account_id = :account_id
                    GROUP BY status
                    ORDER BY status
                    """
                ),
                {"account_id": ACCOUNT_ID},
            )
        ).fetchall()
        if not rows:
            print("(empty)")
        else:
            for status, cnt in rows:
                print(status, cnt)

        print("\n=== 最近12条 autonomous_execution_intent ===")
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, signal_id, symbol, action, qty, status, reason, created_at
                    FROM autonomous_execution_intent
                    WHERE account_id = :account_id
                    ORDER BY id DESC
                    LIMIT 12
                    """
                ),
                {"account_id": ACCOUNT_ID},
            )
        ).fetchall()
        if not rows:
            print("(empty)")
        else:
            for r in rows:
                print(r)


if __name__ == "__main__":
    asyncio.run(main())
