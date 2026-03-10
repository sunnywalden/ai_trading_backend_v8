"""手动收口卡在 CLOSING 的 Position。

示例：
    python scripts/maintenance/reconcile_stale_closing_positions.py
    python scripts/maintenance/reconcile_stale_closing_positions.py --account-id 21272246230273657
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import asyncio
import json

from app.models.db import SessionLocal, close_db_resources
from app.services.broker_order_sync_service import reconcile_stale_closing_positions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="手动收口卡在 CLOSING 的 Position")
    parser.add_argument(
        "--account-id",
        required=False,
        help="可选：指定账户 ID；不传则自动获取当前券商账户",
    )
    return parser


async def _main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    async with SessionLocal() as session:
        result = await reconcile_stale_closing_positions(
            session,
            account_id=args.account_id,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = asyncio.run(_main())
    finally:
        try:
            asyncio.run(close_db_resources())
        except Exception:
            pass
    raise SystemExit(exit_code)