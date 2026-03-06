"""diag_post_trade_loop.py — 排查 Post-Trade S12/S13 循环

用法：
  # 查看所有账户最近 25 条处于 S12-S15 的计划
    python scripts/diagnostics/diag_post_trade_loop.py

  # 指定账户
    python scripts/diagnostics/diag_post_trade_loop.py --account-id 21272246230273657

  # 查看最近 50 条，并打印每条最近 8 条 FSM 日志
    python scripts/diagnostics/diag_post_trade_loop.py --limit 50 --log-limit 8

  # 仅看疑似 S12/S13 循环的计划
    python scripts/diagnostics/diag_post_trade_loop.py --only-loop
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import asyncio
from collections import Counter
from datetime import datetime
from typing import Iterable

import app.models.strategy  # noqa: F401  # 预加载关系，避免 mapper 初始化问题
from sqlalchemy import desc, select

from app.models.db import SessionLocal
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.trade_journal import TradeJournal
from app.models.trading_plan import TradingPlan
from app.schemas.lifecycle import PIPELINE_STAGE_NAMES


POST_TRADE_STAGES = (12, 13, 14, 15)


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _stage_name(stage: int | None) -> str:
    if stage is None:
        return "NULL"
    return f"S{stage}-{PIPELINE_STAGE_NAMES.get(stage, '?')}"


def _looks_like_s12_s13_loop(states: Iterable[str]) -> bool:
    filtered = [s for s in states if s in {"STAGE_12", "STAGE_13", "STAGE_14", "STAGE_15", "STAGE_16"}]
    if len(filtered) < 4:
        return False

    has_forward = any(a == "STAGE_12" and b == "STAGE_13" for a, b in zip(filtered, filtered[1:]))
    has_backward = any(a in {"STAGE_13", "STAGE_14", "STAGE_15", "STAGE_16"} and b == "STAGE_12" for a, b in zip(filtered, filtered[1:]))
    return has_forward and has_backward


async def main(account_id: str | None, limit: int, log_limit: int, only_loop: bool) -> None:
    async with SessionLocal() as db:
        stmt = (
            select(TradingPlan)
            .where(TradingPlan.pipeline_stage.in_(POST_TRADE_STAGES))
            .order_by(desc(TradingPlan.updated_at), desc(TradingPlan.id))
            .limit(limit)
        )
        if account_id:
            stmt = stmt.where(TradingPlan.account_id == account_id)

        plans = (await db.execute(stmt)).scalars().all()
        if not plans:
            print("未找到处于 S12-S15 的计划。")
            return

        print(f"=== Post-Trade 计划概览（count={len(plans)}）===")
        stage_counter = Counter(int(p.pipeline_stage) for p in plans if p.pipeline_stage is not None)
        for stage, cnt in sorted(stage_counter.items()):
            print(f"  {_stage_name(stage)}: {cnt}")
        print()

        matched = 0
        for plan in plans:
            log_stmt = (
                select(FsmTransitionLog)
                .where(FsmTransitionLog.plan_id == plan.id)
                .where(FsmTransitionLog.fsm_type == "PLAN")
                .order_by(desc(FsmTransitionLog.occurred_at), desc(FsmTransitionLog.id))
                .limit(log_limit)
            )
            logs = (await db.execute(log_stmt)).scalars().all()
            ordered_logs = list(reversed(logs))
            state_path = [log.to_state for log in ordered_logs]
            is_loop = _looks_like_s12_s13_loop(state_path)

            if only_loop and not is_loop:
                continue

            matched += 1
            journal_stmt = (
                select(TradeJournal)
                .where(TradeJournal.plan_id == plan.id)
                .order_by(desc(TradeJournal.created_at), desc(TradeJournal.id))
                .limit(1)
            )
            journal = (await db.execute(journal_stmt)).scalar_one_or_none()

            tag_info = plan.plan_tags if isinstance(plan.plan_tags, dict) else {}
            pipeline_completed_at = tag_info.get("pipeline_completed_at")

            print(
                f"[plan#{plan.id}] {plan.symbol} account={plan.account_id} "
                f"stage={_stage_name(plan.pipeline_stage)} status={plan.plan_status} "
                f"entered={_fmt_dt(plan.stage_entered_at)} loop={is_loop}"
            )
            if pipeline_completed_at:
                print(f"  pipeline_completed_at: {pipeline_completed_at}")
            if journal is not None:
                print(
                    f"  journal: status={journal.journal_status} entry={journal.entry_date} "
                    f"exit={journal.exit_date} pnl={journal.realized_pnl}"
                )
            else:
                print("  journal: -")

            if not ordered_logs:
                print("  fsm_logs: -")
            else:
                print("  fsm_logs:")
                for log in ordered_logs:
                    print(
                        f"    {_fmt_dt(log.occurred_at)} | {log.from_state or '-'} -> {log.to_state}"
                        f" | reason={log.trigger_reason or '-'}"
                    )
            print()

        if only_loop:
            print(f"疑似循环计划数: {matched}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="排查 S12/S13 post-trade 循环")
    parser.add_argument("--account-id", help="可选：仅查看指定账户")
    parser.add_argument("--limit", type=int, default=25, help="最多查看多少条计划，默认 25")
    parser.add_argument("--log-limit", type=int, default=6, help="每条计划打印最近多少条 FSM 日志，默认 6")
    parser.add_argument("--only-loop", action="store_true", help="仅打印疑似 S12/S13 循环的计划")
    args = parser.parse_args()
    asyncio.run(main(args.account_id, args.limit, args.log_limit, args.only_loop))