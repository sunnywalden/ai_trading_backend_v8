"""验证归因修复效果：各时间窗口能否正确返回数据"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import sys
sys.path.insert(0, "/Users/admin/IdeaProjects/ai_trading_backend_v8")

import app.models.strategy  # noqa
from app.models.db import SessionLocal
from app.services.trade_attribution_engine import trade_attribution_engine


async def main():
    async with SessionLocal() as db:
        print("=== 归因主表 get_summary (基于 traded_at) ===")
        for days in [7, 14, 30, 60]:
            result = await trade_attribution_engine.get_summary(db, days=days)
            breakdown = result.get("breakdown") or []
            print(f"  [{days}天] breakdown_count={len(breakdown)} items={[(b['category'], b['count']) for b in breakdown]}")

        print()
        print("=== fallback list_from_journal (基于 exit_date) ===")
        for days in [7, 14, 30, 60]:
            items, total = await trade_attribution_engine.list_from_journal(db, days=days, limit=5)
            print(f"  [{days}天] total={total} items_sample={[i.get('symbol') for i in items[:3]]}")

        print()
        print("=== fallback get_summary_from_journal (基于 exit_date) ===")
        for days in [7, 14, 30, 60]:
            result = await trade_attribution_engine.get_summary_from_journal(db, days=days)
            breakdown = result.get("breakdown") or []
            print(f"  [{days}天] breakdown_count={len(breakdown)} items={[(b['category'], b['count']) for b in breakdown]}")


asyncio.run(main())
