"""券商订单状态对账服务（含手动撤单回写）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, desc, distinct, func, or_, select, update
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

        # 查寻所有处于活跃或异常中间态的计划 (S7, S8, S12)
        plans_res = await session.execute(
            select(TradingPlan).where(
                and_(
                    TradingPlan.account_id == real_account_id,
                    or_(
                        TradingPlan.pipeline_stage.in_([7, 8, 12]),
                        TradingPlan.plan_status.in_(["ACTIVE", "EXECUTED", "AUTO_EXECUTING"])
                    )
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
                new_stage = 12  # 持仓监控
                new_status = "EXECUTED"
            elif sig.status == SignalStatus.CANCELLED:
                new_stage = 16  # 已归档
                new_status = "REVOKED"
            elif sig.status == SignalStatus.REJECTED:
                new_stage = 16  # 已归档
                new_status = "FAILED"
            elif sig.status == SignalStatus.VALIDATED:
                # 依然在验证中但没有 order_id，可以维持原状或根据业务逻辑重置
                pass

            if new_stage is not None and (new_stage != plan.pipeline_stage or new_status != plan.plan_status):
                old_stage = plan.pipeline_stage
                plan.pipeline_stage = new_stage
                plan.stage_entered_at = datetime.now(timezone.utc)
                if new_status:
                    plan.plan_status = new_status
                
                # 记录 FSM 日志
                session.add(FsmTransitionLog(
                    plan_id=plan.id,
                    fsm_type="PLAN",
                    from_state=f"STAGE_{old_stage}" if old_stage is not None else "UNKNOWN",
                    to_state=f"STAGE_{new_stage}",
                    trigger_reason="Broker status sync (Manual Cancel/Fill Sync)",
                ))

    await session.commit()

    # 4) 【信号状态补救】处理 order_id 已被清空但 status 仍为 EXECUTED 的信号
    #    场景：信号曾经 EXECUTING → 某次对账时 order_id 被置 None，但 status 未更新
    #    通过 AutonomyAuditLog.revoked_at 来判断该 symbol 的订单是否已被取消
    revoked_audit_rows = await session.execute(
        select(AutonomyAuditLog.symbol, AutonomyAuditLog.created_at)
        .where(AutonomyAuditLog.account_id == real_account_id)
        .where(AutonomyAuditLog.revoked_at.is_not(None))
        .where(AutonomyAuditLog.created_at >= since)
        .where(AutonomyAuditLog.symbol.is_not(None))
    )
    revoked_symbols_ts = {row[0]: row[1] for row in revoked_audit_rows.fetchall()}

    orphan_executed_signals = (await session.execute(
        select(TradingSignal)
        .where(TradingSignal.account_id == real_account_id)
        .where(TradingSignal.status == SignalStatus.EXECUTED)
        .where(TradingSignal.order_id.is_(None))
        .where(TradingSignal.symbol.in_(list(revoked_symbols_ts.keys())))
    )).scalars().all()

    orphan_fixed = 0
    for sig in orphan_executed_signals:
        sig.status = SignalStatus.CANCELLED
        session.add(sig)
        orphan_fixed += 1

    # 5) 【交易日志补建】为所有已 revoked 的审计记录补建缺失的 TradeJournal 条目
    from app.models.trade_journal import TradeJournal
    journal_created = 0
    for audit_row in (await session.execute(
        select(AutonomyAuditLog)
        .where(AutonomyAuditLog.account_id == real_account_id)
        .where(AutonomyAuditLog.revoked_at.is_not(None))
        .where(AutonomyAuditLog.created_at >= since)
        .where(AutonomyAuditLog.symbol.is_not(None))
    )).scalars().all():
        existing_check = await session.execute(
            select(func.count(TradeJournal.id)).where(
                and_(
                    TradeJournal.account_id == real_account_id,
                    TradeJournal.symbol == audit_row.symbol,
                    TradeJournal.created_at >= audit_row.created_at - timedelta(hours=1),
                    TradeJournal.created_at <= audit_row.created_at + timedelta(hours=1),
                )
            )
        )
        if (existing_check.scalar() or 0) == 0:
            try:
                from datetime import date as _date
                from app.models.trading_plan import TradingPlan as _TradingPlan
                direction = "BUY" if audit_row.decision_type in ("BUY", "LONG") else "SELL"

                # 查最近一条 AI 自主计划，取真实建仓价和仓位大小
                plan_lookup_res = await session.execute(
                    select(_TradingPlan)
                    .where(
                        and_(
                            _TradingPlan.account_id == real_account_id,
                            _TradingPlan.symbol == audit_row.symbol,
                            _TradingPlan.source == "AI_AUTONOMOUS",
                        )
                    )
                    .order_by(desc(_TradingPlan.created_at))
                    .limit(1)
                )
                related_plan = plan_lookup_res.scalar_one_or_none()
                actual_entry = float(related_plan.entry_price) if related_plan and related_plan.entry_price else 0.0
                actual_qty   = float(related_plan.target_position) if related_plan and related_plan.target_position else 0.0
                actual_plan_id = related_plan.id if related_plan else None

                j = TradeJournal(
                    account_id=real_account_id,
                    symbol=audit_row.symbol,
                    direction=direction,
                    entry_date=_date.today(),
                    entry_price=actual_entry,
                    quantity=actual_qty,
                    plan_id=actual_plan_id,
                    journal_status="FAILED",
                    lesson_learned=f"自主交易撤单: {audit_row.revoke_reason or 'Manual Cancel at Broker'}",
                )
                session.add(j)
                journal_created += 1
            except Exception:
                pass  # 日志补建失败不影响主流程

    if orphan_fixed > 0 or journal_created > 0:
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
        "orphan_signals_fixed": orphan_fixed,
        "journal_entries_created": journal_created,
        "remaining_EXECUTING": int(remaining_exec),
        "signals_with_order_id": int(with_order_id),
        "audit_revoked_marked": int(revoked_marked),
    }
