"""检查归因分析数据状态"""
import asyncio
import app.models.strategy
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, or_, and_
from app.models.db import SessionLocal
from app.models.trade_journal import TradeJournal
from app.models.trade_attribution import TradeAttributionEntry


async def main():
    async with SessionLocal() as db:
        # 归因表总量
        attr_total = (await db.execute(select(func.count()).select_from(TradeAttributionEntry))).scalar() or 0

        # journal 总量与时间范围
        total = (await db.execute(select(func.count()).select_from(TradeJournal))).scalar() or 0
        newest = (await db.execute(select(func.max(TradeJournal.created_at)))).scalar()
        oldest = (await db.execute(select(func.min(TradeJournal.created_at)))).scalar()

        # 已平仓：realized_pnl IS NOT NULL
        closed_realized = (await db.execute(
            select(func.count()).select_from(TradeJournal)
            .where(TradeJournal.realized_pnl.is_not(None))
        )).scalar() or 0

        # 已平仓：entry+exit 价格都有
        closed_prices = (await db.execute(
            select(func.count()).select_from(TradeJournal)
            .where(TradeJournal.entry_price.is_not(None), TradeJournal.exit_price.is_not(None))
        )).scalar() or 0

        # 从任何角度看的"已平仓"
        closed_pred = or_(
            TradeJournal.realized_pnl.is_not(None),
            and_(TradeJournal.entry_price.is_not(None), TradeJournal.exit_price.is_not(None))
        )
        closed_any = (await db.execute(
            select(func.count()).select_from(TradeJournal).where(closed_pred)
        )).scalar() or 0

        # 7天内
        since7 = datetime.now(tz=timezone.utc) - timedelta(days=7)
        in_7d = (await db.execute(
            select(func.count()).select_from(TradeJournal)
            .where(TradeJournal.created_at >= since7)
        )).scalar() or 0

        closed_7d = (await db.execute(
            select(func.count()).select_from(TradeJournal)
            .where(TradeJournal.created_at >= since7, closed_pred)
        )).scalar() or 0

        # 30天内
        since30 = datetime.now(tz=timezone.utc) - timedelta(days=30)
        closed_30d = (await db.execute(
            select(func.count()).select_from(TradeJournal)
            .where(TradeJournal.created_at >= since30, closed_pred)
        )).scalar() or 0

        print(f"=== TradeAttributionEntry 归因表 ===")
        print(f"  total={attr_total}")

        print(f"\n=== TradeJournal 交易日志 ===")
        print(f"  total={total}")
        print(f"  oldest={oldest}, newest={newest}")
        print(f"  closed(realized_pnl)={closed_realized}")
        print(f"  closed(entry+exit prices)={closed_prices}")
        print(f"  closed(any)={closed_any}")
        print(f"  in_7d total={in_7d}, closed_7d={closed_7d}")
        print(f"  in_30d closed={closed_30d}")

        print(f"\n=== 最近10条 journal 记录 ===")
        rows = (await db.execute(
            select(
                TradeJournal.id, TradeJournal.symbol, TradeJournal.created_at,
                TradeJournal.realized_pnl, TradeJournal.entry_price, TradeJournal.exit_price,
                TradeJournal.close_reason
            ).order_by(TradeJournal.created_at.desc()).limit(10)
        )).all()
        for r in rows:
            print(f"  id={r.id} {r.symbol} {str(r.created_at)[:19]} "
                  f"realized={r.realized_pnl} entry={r.entry_price} exit={r.exit_price} "
                  f"close_reason={r.close_reason}")


asyncio.run(main())
