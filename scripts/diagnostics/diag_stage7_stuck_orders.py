"""diag_stage7_stuck_orders.py — 排查卡在 S7 下单执行的计划

用法：
  python scripts/diag_stage7_stuck_orders.py
  python scripts/diag_stage7_stuck_orders.py --account-id 21272246230273657
  python scripts/diag_stage7_stuck_orders.py --limit 30 --log-limit 8

输出重点：
  - 当前 S7 计划
  - 对应最新信号状态 / order_id
  - 券商真实持仓中是否还持有该 symbol
  - 建议推进目标（S9 / S12 / S16 / 保持）
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models.strategy  # noqa: F401
from sqlalchemy import desc, select

from app.broker.factory import make_option_broker_client
from app.models.db import SessionLocal
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.trading_plan import TradingPlan
from app.models.trading_signal import TradingSignal
from app.schemas.lifecycle import PIPELINE_STAGE_NAMES
from app.services.broker_order_sync_service import (
    _derive_reconciled_stage,
    _extract_live_position_symbols,
)


def _fmt_dt(value: Optional[datetime]) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _stage_name(stage: Optional[int]) -> str:
    if stage is None:
        return "NULL"
    return f"S{stage}-{PIPELINE_STAGE_NAMES.get(stage, '?')}"


async def main(account_id: Optional[str], limit: int, log_limit: int) -> None:
    broker = make_option_broker_client()
    real_account_id = str(account_id or await broker.get_account_id())

    try:
        raw_positions = await broker.list_underlying_positions(real_account_id)
    except Exception as exc:
        print(f"读取券商持仓失败，将按空仓处理: {exc}")
        raw_positions = []

    live_position_symbols = _extract_live_position_symbols(list(raw_positions or []))

    async with SessionLocal() as db:
        stmt = (
            select(TradingPlan)
            .where(TradingPlan.account_id == real_account_id)
            .where(TradingPlan.pipeline_stage == 7)
            .order_by(desc(TradingPlan.updated_at), desc(TradingPlan.id))
            .limit(limit)
        )
        plans = (await db.execute(stmt)).scalars().all()

        if not plans:
            print(f"账户 {real_account_id} 没有卡在 S7 的计划。")
            return

        print(f"=== 账户 {real_account_id} 的 S7 计划（count={len(plans)}）===")
        print(f"真实持仓 symbols: {sorted(live_position_symbols)[:20]}{' ...' if len(live_position_symbols) > 20 else ''}")
        print()

        target_counter: Counter[str] = Counter()

        for plan in plans:
            sig_stmt = (
                select(TradingSignal)
                .where(TradingSignal.account_id == real_account_id)
                .where(TradingSignal.symbol == plan.symbol)
                .order_by(desc(TradingSignal.created_at), desc(TradingSignal.id))
                .limit(1)
            )
            signal = (await db.execute(sig_stmt)).scalar_one_or_none()

            suggested_stage = None
            suggested_status = None
            suggested_pos_fsm = None
            if signal is not None:
                suggested_stage, suggested_status, suggested_pos_fsm = _derive_reconciled_stage(
                    signal,
                    live_position_symbols,
                )

            if suggested_stage is None:
                suggestion = "保持S7/人工复核"
            else:
                suggestion = f"推进到 {_stage_name(suggested_stage)}"
            target_counter[suggestion] += 1

            print(
                f"[plan#{plan.id}] {plan.symbol} stage={_stage_name(plan.pipeline_stage)} status={plan.plan_status} "
                f"entered={_fmt_dt(plan.stage_entered_at)}"
            )
            print(
                f"  live_position={'YES' if plan.symbol in live_position_symbols else 'NO'} "
                f"position_fsm={plan.position_fsm_state or '-'}"
            )
            if signal is None:
                print("  latest_signal: -")
            else:
                print(
                    f"  latest_signal: id={signal.signal_id} status={getattr(signal.status, 'value', signal.status)} "
                    f"order_id={signal.order_id or '-'} created={_fmt_dt(signal.created_at)}"
                )
                print(
                    f"  reconcile_suggestion: {suggestion}"
                    f" | target_status={suggested_status or '-'} target_position_fsm={suggested_pos_fsm or '-'}"
                )

            log_stmt = (
                select(FsmTransitionLog)
                .where(FsmTransitionLog.plan_id == plan.id)
                .where(FsmTransitionLog.fsm_type == "PLAN")
                .order_by(desc(FsmTransitionLog.occurred_at), desc(FsmTransitionLog.id))
                .limit(log_limit)
            )
            logs = list(reversed((await db.execute(log_stmt)).scalars().all()))
            if logs:
                print("  recent_fsm_logs:")
                for log in logs:
                    print(
                        f"    {_fmt_dt(log.occurred_at)} | {log.from_state or '-'} -> {log.to_state}"
                        f" | reason={log.trigger_reason or '-'}"
                    )
            else:
                print("  recent_fsm_logs: -")
            print()

        print("=== 建议分布 ===")
        for label, cnt in target_counter.items():
            print(f"  {label}: {cnt}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="排查卡在 S7 的计划")
    parser.add_argument("--account-id", help="可选：指定账户")
    parser.add_argument("--limit", type=int, default=25, help="最多查看多少条计划，默认 25")
    parser.add_argument("--log-limit", type=int, default=6, help="每条计划打印最近多少条 FSM 日志，默认 6")
    args = parser.parse_args()
    asyncio.run(main(args.account_id, args.limit, args.log_limit))