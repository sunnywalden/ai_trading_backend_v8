"""全局数据流诊断脚本 - 检查所有核心数据的填写状态"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import sys
sys.path.insert(0, "/Users/admin/IdeaProjects/ai_trading_backend_v8")

import app.models.strategy  # noqa
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, or_, and_, text
from app.models.db import SessionLocal
from app.models.trading_signal import TradingSignal
from app.models.trading_plan import TradingPlan
from app.models.trade_journal import TradeJournal
from app.models.trade_attribution import TradeAttributionEntry


async def banner(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def main():
    async with SessionLocal() as db:

        # ─────────────────────────────────────────────
        await banner("1. TradingSignal 信号 数据完整性")
        total_sig = (await db.execute(select(func.count()).select_from(TradingSignal))).scalar() or 0
        cols_sig = {
            "actual_return": TradingSignal.actual_return,
            "pnl_pct": TradingSignal.pnl_pct,
            "expected_return": TradingSignal.expected_return,
            "factor_scores": TradingSignal.factor_scores,
            "signal_strength": TradingSignal.signal_strength,
            "signal_id": TradingSignal.signal_id,
        }
        print(f"  total={total_sig}")
        for col_name, col in cols_sig.items():
            cnt = (await db.execute(
                select(func.count()).select_from(TradingSignal).where(col.is_not(None))
            )).scalar() or 0
            pct = cnt / total_sig * 100 if total_sig else 0
            status = "✅" if pct > 50 else ("⚠️" if pct > 0 else "❌")
            print(f"  {status} {col_name}: {cnt}/{total_sig} ({pct:.0f}%)")

        # 有无 actual_return 回填机制的信号
        sig_old = (await db.execute(
            select(func.count()).select_from(TradingSignal)
            .where(
                TradingSignal.actual_return.is_(None),
                TradingSignal.created_at < datetime.now(tz=timezone.utc) - timedelta(days=5)
            )
        )).scalar() or 0
        print(f"  ❓ 已创建>5天但 actual_return 仍为 NULL: {sig_old} 条（应已有回报）")

        # ─────────────────────────────────────────────
        await banner("2. TradingPlan 交易计划 流水线")
        total_plan = (await db.execute(select(func.count()).select_from(TradingPlan))).scalar() or 0
        print(f"  total={total_plan}")

        # pipeline_stage 分布
        stage_rows = (await db.execute(
            select(TradingPlan.pipeline_stage, func.count().label("cnt"))
            .group_by(TradingPlan.pipeline_stage)
            .order_by(TradingPlan.pipeline_stage)
        )).all()
        stage_names = {
            0:"S0-初始", 7:"S7-下单执行", 8:"S8-算法执行", 9:"S9-持仓监控",
            10:"S10-仓位调整", 11:"S11-离场触发", 12:"S12-订单结算",
            13:"S13-归因分析", 14:"S14-洞察更新", 15:"S15-AB实验", 16:"S16-已完成"
        }
        for r in stage_rows:
            name = stage_names.get(r.pipeline_stage or 0, f"S{r.pipeline_stage}")
            print(f"  S{r.pipeline_stage or '?'} {name}: {r.cnt}")

        # 关键缺失字段
        plan_cols = {
            "pipeline_stage": TradingPlan.pipeline_stage,
            "stage_entered_at": TradingPlan.stage_entered_at,
            "position_fsm_state": TradingPlan.position_fsm_state,
            "entry_price": TradingPlan.entry_price,
            "exit_price": TradingPlan.exit_price,
        }
        print()
        for col_name, col in plan_cols.items():
            cnt = (await db.execute(
                select(func.count()).select_from(TradingPlan).where(col.is_not(None))
            )).scalar() or 0
            pct = cnt / total_plan * 100 if total_plan else 0
            status = "✅" if pct > 80 else ("⚠️" if pct > 0 else "❌")
            print(f"  {status} {col_name}: {cnt}/{total_plan} ({pct:.0f}%)")

        # 已完成计划但没有 exit_price
        done_no_exit = (await db.execute(
            select(func.count()).select_from(TradingPlan)
            .where(
                TradingPlan.plan_status.in_(["EXECUTED", "REVOKED", "FAILED", "CANCELLED", "EXPIRED"]),
                TradingPlan.exit_price.is_(None),
            )
        )).scalar() or 0
        print(f"  ❓ 已终态但 exit_price=NULL: {done_no_exit}")

        # ─────────────────────────────────────────────
        await banner("3. TradeJournal 交易日志")
        total_journal = (await db.execute(select(func.count()).select_from(TradeJournal))).scalar() or 0
        print(f"  total={total_journal}")

        j_cols = {
            "entry_price": TradeJournal.entry_price,
            "exit_price": TradeJournal.exit_price,
            "realized_pnl": TradeJournal.realized_pnl,
            "entry_date": TradeJournal.entry_date,
            "exit_date": TradeJournal.exit_date,
            "signal_id": TradeJournal.signal_id,
            "plan_id": TradeJournal.plan_id,
        }
        for col_name, col in j_cols.items():
            cnt = (await db.execute(
                select(func.count()).select_from(TradeJournal).where(col.is_not(None))
            )).scalar() or 0
            pct = cnt / total_journal * 100 if total_journal else 0
            status = "✅" if pct > 80 else ("⚠️" if pct > 0 else "❌")
            print(f"  {status} {col_name}: {cnt}/{total_journal} ({pct:.0f}%)")

        # 有计划但 journal 中没有对应记录
        plan_ids_with_journal = set(
            (await db.execute(select(TradeJournal.plan_id).where(TradeJournal.plan_id.is_not(None)))).scalars().all()
        )
        executed_plans = (await db.execute(
            select(func.count()).select_from(TradingPlan)
            .where(TradingPlan.plan_status.in_(["EXECUTED", "REVOKED", "FAILED", "CANCELLED", "EXPIRED"]))
        )).scalar() or 0
        print(f"\n  ❓ 已终态交易计划 {executed_plans} 个，journal 中有 plan_id 关联: {len(plan_ids_with_journal)} 个")

        # journal 状态分布
        status_rows = (await db.execute(
            select(TradeJournal.journal_status, func.count().label("cnt"))
            .group_by(TradeJournal.journal_status)
        )).all()
        print(f"  journal_status 分布: {[(r.journal_status, r.cnt) for r in status_rows]}")

        # ─────────────────────────────────────────────
        await banner("4. TradeAttributionEntry 归因")
        total_attr = (await db.execute(select(func.count()).select_from(TradeAttributionEntry))).scalar() or 0
        print(f"  total={total_attr}")
        print(f"  已平仓 journal={25}, 归因记录={total_attr}  ({'✅ 匹配' if total_attr >= 25 else '❌ 缺失'})")

        traded_at_filled = (await db.execute(
            select(func.count()).select_from(TradeAttributionEntry)
            .where(TradeAttributionEntry.traded_at.is_not(None))
        )).scalar() or 0
        print(f"  traded_at 已填: {traded_at_filled}/{total_attr}")

        # 没有归因记录的已平仓 journal
        # ─────────────────────────────────────────────
        await banner("5. 系统时间参考")
        print(f"  now_utc = {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # 最近信号创建时间、最近 journal 更新时间
        newest_signal = (await db.execute(select(func.max(TradingSignal.created_at)))).scalar()
        newest_plan = (await db.execute(select(func.max(TradingPlan.updated_at)))).scalar()
        newest_journal = (await db.execute(select(func.max(TradeJournal.created_at)))).scalar()
        print(f"  最新信号: {newest_signal}")
        print(f"  最新计划: {newest_plan}")
        print(f"  最新日志: {newest_journal}")


asyncio.run(main())
