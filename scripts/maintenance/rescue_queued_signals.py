"""
修复脚本：重置因进程重启卡在 QUEUED 状态超过 2h 的 TradingSignal → VALIDATED
（下次 autonomous_engine 运行时会重新处理这些信号）
"""
import asyncio
import sys
sys.path.insert(0, '/Users/admin/IdeaProjects/ai_trading_backend_v8')

async def main():
    from app.models.db import SessionLocal
    from sqlalchemy import text
    from datetime import datetime, timezone, timedelta

    stuck_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)

    async with SessionLocal() as db:
        # 先查看有哪些信号会被重置
        r = await db.execute(text(
            "SELECT id, signal_id, symbol, status, created_at "
            "FROM trading_signals "
            "WHERE status = 'QUEUED' "
            f"AND created_at <= '{stuck_cutoff.strftime('%Y-%m-%d %H:%M:%S')}' "
            "ORDER BY created_at DESC"
        ))
        rows = r.fetchall()
        print(f"Signals to rescue ({len(rows)} total):")
        for row in rows:
            print(f"  db_id={row[0]:6d}  symbol={row[2]:6s}  status={row[3]}  created={row[4]}")

        if not rows:
            print("No stuck signals found.")
            return

        # 执行重置
        result = await db.execute(text(
            "UPDATE trading_signals "
            "SET status = 'VALIDATED' "
            "WHERE status = 'QUEUED' "
            f"AND created_at <= '{stuck_cutoff.strftime('%Y-%m-%d %H:%M:%S')}'"
        ))
        await db.commit()
        print(f"\n✓ Reset {result.rowcount} stuck QUEUED signals → VALIDATED")

        # 验证
        r2 = await db.execute(text(
            "SELECT status, COUNT(*) c FROM trading_signals GROUP BY status ORDER BY c DESC"
        ))
        print("\nCurrent signal status distribution:")
        for row in r2.fetchall():
            print(f"  {str(row[0]):20s}  {row[1]:4d}")

asyncio.run(main())
