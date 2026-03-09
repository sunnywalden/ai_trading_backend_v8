"""诊断：回补后 positions 表与 autonomous_execution_intent 的一致性核查"""

import asyncio
import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("ENV", "production")

from sqlalchemy import text

from app.models.db import SessionLocal


async def diag():
    async with SessionLocal() as db:
        # 1. positions 表当前内容
        r = await db.execute(
            text(
                "SELECT id, symbol, status, direction, open_qty, total_qty, closed_qty "
                "FROM positions ORDER BY id"
            )
        )
        rows = r.fetchall()
        print(f"=== positions ({len(rows)} rows) ===")
        for row in rows:
            print(
                f"  id={row[0]:3d}  {row[1]:6s}  status={row[2]:22s}  "
                f"open_qty={row[4]:10.4f}  total={row[5]:10.4f}  closed={row[6]:10.4f}"
            )

        # 2. 非港股 intent 汇总 (所有 status/action)
        r2 = await db.execute(
            text(
                "SELECT symbol, action, status, SUM(qty), COUNT(*) "
                "FROM autonomous_execution_intent "
                "WHERE symbol NOT REGEXP '^[0-9]{5}$' "
                "GROUP BY symbol, action, status "
                "ORDER BY symbol, action, status"
            )
        )
        rows2 = r2.fetchall()
        print(f"\n=== intent summary (non-HK, all status) ===")
        for r in rows2:
            print(
                f"  {r[0]:6s}  action={r[1]:12s}  status={r[2]:20s}  "
                f"sum_qty={float(r[3]):10.4f}  cnt={r[4]}"
            )

        # 3. 检查 trading_plan 里有无标的有持仓但无 intent 记录
        r3 = await db.execute(
            text(
                "SELECT symbol, plan_status, COUNT(*) as cnt, "
                "   SUM(target_position) as total_pos, "
                "   MAX(entry_price) as max_entry "
                "FROM trading_plan "
                "WHERE symbol NOT REGEXP '^[0-9]{5}$' "
                "  AND plan_status NOT IN ('REVOKED', 'EXPIRED') "
                "GROUP BY symbol, plan_status "
                "ORDER BY symbol"
            )
        )
        rows3 = r3.fetchall()
        print(f"\n=== trading_plan (non-HK, non-revoked/expired) ===")
        for r in rows3:
            print(
                f"  {r[0]:6s}  plan_status={r[1]:20s}  cnt={r[2]}  "
                f"total_pos={r[3]}  max_entry={r[4]}"
            )


asyncio.run(diag())
