"""检查交易可观测模块数据状态"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import sys

sys.path.insert(0, '/Users/admin/IdeaProjects/ai_trading_backend_v8')

from app.models.trading_plan import TradingPlan

TRADING_PLAN_TABLE = TradingPlan.__tablename__

async def main():
    from sqlalchemy import text

    from app.models.db import SessionLocal, close_db_resources

    try:
        async with SessionLocal() as db:
            # TradingPlan 按状态分组
            r = await db.execute(text(
                "SELECT plan_status, COUNT(*) c, MAX(created_at) latest "
                f"FROM {TRADING_PLAN_TABLE} GROUP BY plan_status ORDER BY latest DESC"
            ))
            print("=== TradingPlan by status ===")
            for row in r.fetchall():
                print(f"  {str(row[0]):20s}  count={row[1]:4d}  latest={row[2]}")

            # TradingSignal 按状态分组
            r2 = await db.execute(text(
                "SELECT status, COUNT(*) c, MAX(created_at) latest "
                "FROM trading_signals GROUP BY status ORDER BY latest DESC LIMIT 10"
            ))
            print("\n=== TradingSignal by status ===")
            for row in r2.fetchall():
                print(f"  {str(row[0]):20s}  count={row[1]:4d}  latest={row[2]}")

            # 昨天以来新增数量
            r3 = await db.execute(text(
                "SELECT COUNT(*) FROM trading_signals WHERE created_at >= '2026-02-27 00:00:00'"
            ))
            print(f"\n=== Signals since 2026-02-27 00:00 ===  {r3.scalar()}")

            r4 = await db.execute(text(
                f"SELECT COUNT(*) FROM {TRADING_PLAN_TABLE} "
                "WHERE created_at >= '2026-02-27 00:00:00'"
            ))
            print(f"=== Plans since   2026-02-27 00:00 ===  {r4.scalar()}")

            # 最新5条 Plan
            r5 = await db.execute(text(
                "SELECT id, symbol, plan_status, pipeline_stage, created_at "
                f"FROM {TRADING_PLAN_TABLE} ORDER BY created_at DESC LIMIT 5"
            ))
            print("\n=== Latest 5 TradingPlan rows ===")
            for row in r5.fetchall():
                print(f"  id={row[0]:6d}  {row[1]:6s}  {str(row[2]):20s}  stage={row[3]}  created={row[4]}")

            # FSM position_lifecycle 状态
            try:
                r6 = await db.execute(text(
                    "SELECT fsm_state, COUNT(*) c, MAX(updated_at) latest "
                    "FROM position_lifecycle GROUP BY fsm_state ORDER BY latest DESC"
                ))
                print("\n=== PositionLifecycle FSM states ===")
                for row in r6.fetchall():
                    print(f"  {str(row[0]):20s}  count={row[1]:4d}  latest={row[2]}")
            except Exception as e:
                print(f"\n[position_lifecycle table error]: {e}")
    finally:
        await close_db_resources()


if __name__ == "__main__":
    asyncio.run(main())
