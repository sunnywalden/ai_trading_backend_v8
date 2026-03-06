"""生产上线辅助：修复交易生命周期数据。

能力覆盖：
1. 可选触发一次券商对账（stage7/stage8 活跃计划收敛）
2. 识别并归正已归档计划的终态语义（FAILED / EXPIRED / REVOKED）
3. 默认 dry-run，仅输出建议；显式传 --apply 才会写库

示例：
  python scripts/reconcile_lifecycle_rollout.py
    # 不指定 --account-id 时，自动获取当前券商账户
  python scripts/reconcile_lifecycle_rollout.py --account-id 21272246230273657 --apply
  python scripts/reconcile_lifecycle_rollout.py --plan-ids 49,50,53 --apply --skip-broker-sync
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models.strategy  # noqa: F401
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.models.db import SessionLocal, close_db_resources
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.trading_plan import TradingPlan
from app.services.broker_order_sync_service import (
    _classify_terminal_status,
    _derive_plan_resolution,
    _extract_live_position_symbols,
    _find_plan_intent_and_audit,
    reconcile_broker_order_status,
)


@dataclass
class PlanRecommendation:
    plan_id: int
    symbol: str
    current_stage: Optional[int]
    current_status: Optional[str]
    current_position_fsm: Optional[str]
    target_stage: Optional[int]
    target_status: Optional[str]
    target_position_fsm: Optional[str]
    action_type: str
    reason: Optional[str]
    changed: bool


@dataclass
class PlanSnapshot:
    plan_id: int
    symbol: str
    pipeline_stage: Optional[int]
    plan_status: Optional[str]
    position_fsm_state: Optional[str]
    updated_at: Optional[str]


def _parse_plan_ids(raw: Optional[str]) -> tuple[int, ...]:
    if not raw:
        return ()
    items: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        items.append(int(chunk))
    return tuple(sorted(set(items)))


async def _resolve_account_id(account_id: Optional[str]) -> str:
    if account_id:
        return str(account_id)
    broker = make_option_broker_client()
    return str(await broker.get_account_id())


async def _load_live_position_symbols(account_id: str) -> set[str]:
    broker = make_option_broker_client()
    try:
        raw_positions = await broker.list_underlying_positions(account_id)
    except Exception:
        raw_positions = []
    return _extract_live_position_symbols(list(raw_positions or []))


async def _load_scope_plans(
    session: AsyncSession,
    account_id: str,
    plan_ids: tuple[int, ...],
    lookback_days: int,
    limit: int,
) -> list[TradingPlan]:
    stmt = select(TradingPlan).where(TradingPlan.account_id == account_id)
    if plan_ids:
        stmt = stmt.where(TradingPlan.id.in_(plan_ids))
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        stmt = stmt.where(
            or_(
                TradingPlan.pipeline_stage.in_((7, 8)),
                and_(
                    TradingPlan.pipeline_stage >= 16,
                    TradingPlan.position_fsm_state == "CLOSED",
                    TradingPlan.plan_status.in_(("FAILED", "REVOKED", "EXPIRED")),
                ),
            )
        ).where(
            or_(
                TradingPlan.updated_at >= cutoff.replace(tzinfo=None),
                TradingPlan.created_at >= cutoff.replace(tzinfo=None),
            )
        )
    stmt = stmt.order_by(TradingPlan.updated_at.desc(), TradingPlan.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def _recommend_for_plan(
    session: AsyncSession,
    account_id: str,
    plan: TradingPlan,
    live_position_symbols: set[str],
) -> PlanRecommendation:
    current_stage = plan.pipeline_stage
    current_status = plan.plan_status
    current_position_fsm = plan.position_fsm_state

    if (plan.pipeline_stage or 0) in (7, 8):
        target_stage, target_status, target_position_fsm, reason = await _derive_plan_resolution(
            session,
            account_id,
            plan,
            live_position_symbols,
        )
        changed = any(
            [
                target_stage is not None and target_stage != current_stage,
                target_status is not None and target_status != current_status,
                target_position_fsm is not None and target_position_fsm != current_position_fsm,
            ]
        )
        return PlanRecommendation(
            plan_id=plan.id,
            symbol=plan.symbol,
            current_stage=current_stage,
            current_status=current_status,
            current_position_fsm=current_position_fsm,
            target_stage=target_stage,
            target_status=target_status,
            target_position_fsm=target_position_fsm,
            action_type="active_reconcile",
            reason=reason,
            changed=changed,
        )

    intent, audit = await _find_plan_intent_and_audit(session, account_id, plan)
    reason = None
    if audit is not None and audit.revoked_at is not None:
        reason = audit.revoke_reason
    elif intent is not None and str(intent.status or "").upper() == "FAILED":
        reason = intent.reason

    target_status = _classify_terminal_status(reason) if reason else current_status
    changed = (target_status or current_status) != current_status
    return PlanRecommendation(
        plan_id=plan.id,
        symbol=plan.symbol,
        current_stage=current_stage,
        current_status=current_status,
        current_position_fsm=current_position_fsm,
        target_stage=current_stage,
        target_status=target_status,
        target_position_fsm=current_position_fsm,
        action_type="terminal_normalize",
        reason=reason,
        changed=changed,
    )


async def _snapshot_plans(
    session: AsyncSession,
    account_id: str,
    plan_ids: tuple[int, ...],
    lookback_days: int,
    limit: int,
) -> list[PlanSnapshot]:
    plans = await _load_scope_plans(session, account_id, plan_ids, lookback_days, limit)
    return [
        PlanSnapshot(
            plan_id=plan.id,
            symbol=plan.symbol,
            pipeline_stage=plan.pipeline_stage,
            plan_status=plan.plan_status,
            position_fsm_state=plan.position_fsm_state,
            updated_at=(plan.updated_at.isoformat() if isinstance(plan.updated_at, datetime) else str(plan.updated_at)),
        )
        for plan in plans
    ]


async def _apply_terminal_normalizations(
    session: AsyncSession,
    recommendations: list[PlanRecommendation],
) -> int:
    by_id = {
        plan.id: plan
        for plan in (
            await session.execute(
                select(TradingPlan).where(TradingPlan.id.in_([item.plan_id for item in recommendations]))
            )
        ).scalars().all()
    }
    changed = 0
    now = datetime.now(timezone.utc)

    for rec in recommendations:
        if rec.action_type != "terminal_normalize" or not rec.changed:
            continue
        plan = by_id.get(rec.plan_id)
        if plan is None:
            continue

        old_stage = plan.pipeline_stage
        old_status = plan.plan_status
        old_position_fsm = plan.position_fsm_state
        changed_any = False

        if rec.target_stage is not None and rec.target_stage != plan.pipeline_stage:
            plan.pipeline_stage = rec.target_stage
            plan.stage_entered_at = now
            changed_any = True

        if rec.target_position_fsm is not None and rec.target_position_fsm != plan.position_fsm_state:
            plan.position_fsm_state = rec.target_position_fsm
            changed_any = True

        if rec.target_status is not None and rec.target_status != plan.plan_status:
            plan.plan_status = rec.target_status
            changed_any = True

        if changed_any:
            session.add(
                FsmTransitionLog(
                    plan_id=plan.id,
                    fsm_type="PLAN",
                    from_state=f"STAGE_{old_stage}" if old_stage is not None else "UNKNOWN",
                    to_state=f"STAGE_{plan.pipeline_stage}" if plan.pipeline_stage is not None else "UNKNOWN",
                    engine="manual",
                    trigger_reason=(
                        f"Lifecycle rollout reconcile: {old_status}/{old_position_fsm} -> "
                        f"{plan.plan_status}/{plan.position_fsm_state}; reason={rec.reason or '-'}"
                    ),
                )
            )
            changed += 1

    return changed


async def run(args: argparse.Namespace) -> dict:
    real_account_id = await _resolve_account_id(args.account_id)
    plan_ids = _parse_plan_ids(args.plan_ids)
    summary: dict = {
        "account_id": real_account_id,
        "apply": bool(args.apply),
        "plan_ids": list(plan_ids),
        "lookback_days": args.lookback_days,
        "limit": args.limit,
        "broker_sync": None,
        "before": [],
        "recommendations": [],
        "applied_terminal_changes": 0,
        "after": [],
    }

    async with SessionLocal() as session:
        summary["before"] = [asdict(item) for item in await _snapshot_plans(session, real_account_id, plan_ids, args.lookback_days, args.limit)]

        if args.apply and not args.skip_broker_sync:
            summary["broker_sync"] = await reconcile_broker_order_status(
                session=session,
                account_id=real_account_id,
                lookback_days=args.lookback_days,
            )

        live_position_symbols = await _load_live_position_symbols(real_account_id)
        plans = await _load_scope_plans(session, real_account_id, plan_ids, args.lookback_days, args.limit)
        recommendations = [
            await _recommend_for_plan(session, real_account_id, plan, live_position_symbols)
            for plan in plans
        ]
        summary["recommendations"] = [asdict(item) for item in recommendations]

        if args.apply:
            summary["applied_terminal_changes"] = await _apply_terminal_normalizations(session, recommendations)
            if summary["applied_terminal_changes"]:
                await session.commit()
            else:
                await session.rollback()
        else:
            await session.rollback()

        summary["after"] = [asdict(item) for item in await _snapshot_plans(session, real_account_id, plan_ids, args.lookback_days, args.limit)]

    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生产上线辅助：修复交易生命周期数据")
    parser.add_argument("--account-id", required=False, help="可选：指定账户 ID；不传则自动获取当前券商账户")
    parser.add_argument("--plan-ids", help="可选：逗号分隔的计划 ID，仅处理这些计划")
    parser.add_argument("--lookback-days", type=int, default=3, help="扫描窗口（天），默认 3")
    parser.add_argument("--limit", type=int, default=200, help="最多扫描多少条计划，默认 200")
    parser.add_argument("--skip-broker-sync", action="store_true", help="跳过券商对账，仅做终态诊断/归正")
    parser.add_argument("--apply", action="store_true", help="执行写库修复；默认仅 dry-run 输出建议")
    return parser


async def _main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    summary = await run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = asyncio.run(_main())
    finally:
        try:
            asyncio.run(close_db_resources())
        except Exception:
            pass
    raise SystemExit(exit_code)
