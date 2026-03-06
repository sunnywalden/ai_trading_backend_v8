"""深度诊断脚本"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import sys
sys.path.insert(0, '/Users/admin/IdeaProjects/ai_trading_backend_v8')

async def main():
    from app.models.db import SessionLocal
    from sqlalchemy import text

    async with SessionLocal() as db:
        # 1. lifecycle 相关表
        r = await db.execute(text("SHOW TABLES LIKE '%lifecycle%'"))
        print("lifecycle tables:", [row[0] for row in r.fetchall()])

        # 2. plan 相关表
        r2 = await db.execute(text("SHOW TABLES LIKE '%plan%'"))
        print("plan tables:", [row[0] for row in r2.fetchall()])

        # 3. QUEUED 信号详情
        r3 = await db.execute(text(
            "SELECT signal_source, signal_type, symbol, status, created_at "
            "FROM trading_signals WHERE status='QUEUED' "
            "ORDER BY created_at DESC LIMIT 5"
        ))
        print("\nQUEUED signals:")
        for row in r3.fetchall():
            print(f"  source={row[0]} type={row[1]} symbol={row[2]} at={row[4]}")

        # 4. REJECTED 信号详情
        r4 = await db.execute(text(
            "SELECT signal_source, signal_type, symbol, status, created_at "
            "FROM trading_signals WHERE status='REJECTED' "
            "ORDER BY created_at DESC LIMIT 5"
        ))
        print("\nREJECTED signals:")
        for row in r4.fetchall():
            print(f"  source={row[0]} type={row[1]} symbol={row[2]} at={row[4]}")

        # 5. 所有表名（前缀过滤）
        r5 = await db.execute(text("SHOW TABLES"))
        all_tables = [row[0] for row in r5.fetchall()]
        print("\nAll tables:", all_tables)

        # 6. signal_to_plan 流程：VALIDATED 的信号有没有对应 plan
        r6 = await db.execute(text(
            "SELECT ts.signal_id, ts.symbol, ts.status, ts.suggested_price, "
            "ts.created_at FROM trading_signals ts "
            "WHERE ts.status IN ('VALIDATED','QUEUED') "
            "ORDER BY ts.created_at DESC LIMIT 5"
        ))
        print("\nVALIDATED/QUEUED signal details:")
        for row in r6.fetchall():
            print(f"  id={row[0]} symbol={row[1]} status={row[2]} price={row[3]} at={row[4]}")

asyncio.run(main())
