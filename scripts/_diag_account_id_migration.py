"""诊断5张证券数据表的account_id列迁移状态及数据分布"""
import asyncio
from sqlalchemy import select, func, text
import app.models.strategy  # noqa: F401
from app.models.db import SessionLocal
from app.models.trading_signal import TradingSignal
from app.models.trade_journal import TradeJournal

TABLES = [
    ("signal_weight_history", "idx_swh_account_date_dim"),
    ("portfolio_factor_exposure", "idx_pfe_account_snap"),
    ("confidence_calibration_snapshot", "idx_ccs_account_date"),
    ("execution_quality_log", "idx_eql_account_symbol"),
    ("decision_post_mortems", "idx_dpm_account_symbol"),
]

async def main():
    async with SessionLocal() as db:
        print("=== 1. DB列名状态检查 ===")
        for tbl, _ in TABLES:
            try:
                r = (await db.execute(text(f"SELECT account_id, COUNT(*) cnt FROM `{tbl}` GROUP BY account_id ORDER BY cnt DESC LIMIT 5"))).all()
                print(f"  {tbl}: account_id col OK -> {r}")
            except Exception:
                try:
                    r = (await db.execute(text(f"SELECT user_id, COUNT(*) cnt FROM `{tbl}` GROUP BY user_id ORDER BY cnt DESC LIMIT 5"))).all()
                    print(f"  {tbl}: STILL user_id col -> {r}")
                except Exception as e2:
                    print(f"  {tbl}: ERROR -> {e2}")

        print("\n=== 2. trading_signal user_id -> account_id 映射 ===")
        mapping = (await db.execute(
            select(TradingSignal.user_id, TradingSignal.account_id, func.count().label("cnt"))
            .where(TradingSignal.account_id.is_not(None))
            .group_by(TradingSignal.user_id, TradingSignal.account_id)
        )).all()
        for m in mapping:
            print(f"  user_id={m.user_id!r} -> account_id={m.account_id!r}  signals={m.cnt}")

        print("\n=== 3. trade_journal account_id 分布 ===")
        jrows = (await db.execute(
            select(TradeJournal.account_id, func.count().label("cnt"))
            .group_by(TradeJournal.account_id)
            .order_by(func.count().desc())
        )).all()
        for r in jrows:
            print(f"  account_id={r.account_id!r}  cnt={r.cnt}")

asyncio.run(main())
