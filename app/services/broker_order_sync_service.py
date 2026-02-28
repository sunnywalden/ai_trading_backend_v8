"""券商订单状态对账服务（含手动撤单回写）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, desc, distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.models.strategy  # noqa: F401  # 预加载关系，避免 TradingSignal mapper 解析 Strategy 失败
from app.broker.factory import make_option_broker_client
from app.engine.order_executor import OrderExecutor
from app.models.autonomy_audit_log import AutonomyAuditLog
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.trading_signal import SignalStatus, TradingSignal


async def reconcile_broker_order_status(
    session: AsyncSession,
    account_id: Optional[str] = None,
    lookback_days: int = 3,
) -> dict[str, Any]:
    """将券商侧订单状态回写到本地数据库。

    覆盖两类场景：
    1) 本地 EXECUTING 订单正常收敛（FILLED/CANCELLED/REJECTED）
    2) 用户在券商 App 手动撤单导致本地未及时感知
    """
    broker = make_option_broker_client()
    real_account_id = str(account_id or await broker.get_account_id())
    lookback_days = max(1, int(lookback_days or 1))

    executor = OrderExecutor(session)

    # 1) 先同步 EXECUTING 信号（已有内置逻辑）
    sync_result = await executor.sync_executing_orders(real_account_id)
    synced_executing = int(sync_result.get("synced", 0) or 0)
    synced_updates = int(sync_result.get("updates", 0) or 0)

    # 2) 再补偿同步最近 N 天存在 order_id 的审计记录 + 信号记录
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    audit_order_rows = await session.execute(
        select(distinct(AutonomyAuditLog.order_id))
        .where(AutonomyAuditLog.account_id == real_account_id)
        .where(AutonomyAuditLog.order_id.is_not(None))
        .where(AutonomyAuditLog.created_at >= since)
    )
    signal_order_rows = await session.execute(
        select(distinct(TradingSignal.order_id))
        .where(TradingSignal.account_id == real_account_id)
        .where(TradingSignal.order_id.is_not(None))
    )

    candidate_ids = {
        str(r[0]) for r in audit_order_rows.fetchall() if r and r[0]
    } | {
        str(r[0]) for r in signal_order_rows.fetchall() if r and r[0]
    }

    cancelled_synced = 0
    filled_synced = 0

    for oid in sorted(candidate_ids):
        status_resp = await broker.get_order_status(real_account_id, oid)
        status = str(status_resp.get("status") or "")
        msg = str(status_resp.get("message") or "")[:200]

        if status in ("CANCELLED", "REJECTED"):
            # 让现有逻辑回写信号状态（会将 EXECUTING -> VALIDATED 并清空失效 order_id）
            await executor.monitor_order_status(real_account_id, oid)

            # 审计日志补充撤销标记
            await session.execute(
                update(AutonomyAuditLog)
                .where(
                    and_(
                        AutonomyAuditLog.account_id == real_account_id,
                        AutonomyAuditLog.order_id == oid,
                        AutonomyAuditLog.revoked_at.is_(None),
                    )
                )
                .values(
                    revoked_at=datetime.now(timezone.utc),
                    revoke_reason=f"broker-manual-cancel-sync: {msg}" if msg else "broker-manual-cancel-sync",
                )
            )

            # 执行意图补充失败状态（若存在）
            await session.execute(
                update(AutonomousExecutionIntent)
                .where(AutonomousExecutionIntent.order_id == oid)
                .values(
                    status="FAILED",
                    reason=f"broker-manual-cancel-sync({msg})" if msg else "broker-manual-cancel-sync",
                )
            )
            cancelled_synced += 1

        elif status == "FILLED":
            await executor.monitor_order_status(real_account_id, oid)
            filled_synced += 1

    # 3) 【关键修正】同步 TradingPlan 的 Pipeline 阶段 (针对 V10.3 看板)
    if cancelled_synced > 0 or filled_synced > 0:
        from app.models.trading_plan import TradingPlan
        from app.models.fsm_transition_log import FsmTransitionLog

        # 查寻所有处于 7 (下单执行) 或 8 (算法执行) 阶段的活跃计划
        plans_res = await session.execute(
            select(TradingPlan).where(
                and_(
                    TradingPlan.account_id == real_account_id,
                    TradingPlan.pipeline_stage.in_([7, 8]),
                    TradingPlan.plan_status.in_(["ACTIVE", "EXECUTED"]),
                )
            )
        )
        for plan in plans_res.scalars().all():
            # 查找该计划发出的最新信号
            sig_res = await session.execute(
                select(TradingSignal)
                .where(TradingSignal.account_id == real_account_id)
                .where(TradingSignal.symbol == plan.symbol)
                .where(TradingSignal.order_id.is_not(None))
                .order_by(desc(TradingSignal.created_at))
                .limit(1)
            )
            sig = sig_res.scalar_one_or_none()
            if not sig: continue

            new_stage = None
            new_status = None
            if sig.status == SignalStatus.EXECUTED:
                new_stage = 12  # 订单结算
            elif sig.status in (SignalStatus.CANCELLED, SignalStatus.FAILED, SignalStatus.VALIDATED):
                new_stage = 16  # 已完成
                new_status = "REVOKED"

            if new_stage is not None and new_stage != plan.pipeline_stage:
                old_stage = plan.pipeline_stage
                plan.pipeline_stage = new_stage
                plan.stage_entered_at = datetime.now(timezone.utc)
                if new_status:
                    plan.plan_status = new_status
                
                # 记录 FSM 日志
                session.add(FsmTransitionLog(
                    plan_id=plan.id,
                    fsm_type="PLAN",
                    from_state=f"STAGE_{old_stage}",
                    to_state=f"STAGE_{new_stage}",
                    trigger_reason="Broker status sync (Manual Cancel/Fill)",
                ))

    await session.commit()

    remaining_exec = (
        await session.execute(
            select(func.count())
            .select_from(TradingSignal)
            .where(TradingSignal.account_id == real_account_id)
            .where(TradingSignal.status == SignalStatus.EXECUTING)
        )
    ).scalar() or 0

    with_order_id = (
        await session.execute(
            select(func.count())
            .select_from(TradingSignal)
            .where(TradingSignal.account_id == real_account_id)
            .where(TradingSignal.order_id.is_not(None))
        )
    ).scalar() or 0

    revoked_marked = (
        await session.execute(
            select(func.count())
            .select_from(AutonomyAuditLog)
            .where(AutonomyAuditLog.account_id == real_account_id)
            .where(AutonomyAuditLog.revoked_at.is_not(None))
            .where(AutonomyAuditLog.created_at >= since)
        )
    ).scalar() or 0

    return {
        "account_id": real_account_id,
        "lookback_days": lookback_days,
        "candidate_order_ids": len(candidate_ids),
        "sync_executing": {
            "signals": synced_executing,
            "updates": synced_updates,
        },
        "cancelled_synced": cancelled_synced,
        "filled_synced": filled_synced,
        "remaining_EXECUTING": int(remaining_exec),
        "signals_with_order_id": int(with_order_id),
        "audit_revoked_marked": int(revoked_marked),
    }
