"""券商订单状态对账服务（含手动撤单回写）。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast

from sqlalchemy import and_, desc, distinct, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.models.strategy  # noqa: F401  # 预加载关系，避免 TradingSignal mapper 解析 Strategy 失败
from app.broker.factory import make_option_broker_client
from app.engine.order_executor import OrderExecutor
from app.models.autonomy_audit_log import AutonomyAuditLog
from app.models.execution_intent import AutonomousExecutionIntent
from app.models.execution_slice import ExecutionSlice, SliceAction, SliceStatus
from app.models.position import Position, PositionStatus
from app.models.trading_signal import SignalStatus, TradingSignal
from app.services.position_lifecycle_manager import PositionLifecycleManager
from app.services.lifecycle_service import lifecycle_service


logger = logging.getLogger(__name__)

_BROKER_RECONCILE_ACTIVE_STAGES = frozenset({7, 8})
_POST_TRADE_STAGE_START = 12
_STAGE7_STALE_CLOSE_AFTER = timedelta(hours=6)


def _is_broker_native_order_id(order_id: Any) -> bool:
    """仅保留可向 Tiger 查询的真实券商订单号。"""
    text = str(order_id or "").strip()
    if not text:
        return False
    # Tiger 当前主链路返回的真实 order_id 为纯数字；SIM_/UUID/本地占位单不应打到券商。
    return text.isdigit()


def _is_plan_reconcile_candidate(plan_stage: Optional[int], plan_status: Optional[str]) -> bool:
    """仅对仍处在下单/执行阶段的计划做券商对账。

    已进入 S12+ 的 post-trade 流水线应交由 PostTradePipelineService 推进，
    券商对账不能再把它们拖回 S12，否则就会出现 S12/S13 来回横跳。
    """
    if plan_stage in _BROKER_RECONCILE_ACTIVE_STAGES:
        return True
    if plan_stage is None and plan_status in {"ACTIVE", "AUTO_EXECUTING", "EXECUTED"}:
        return True
    return False


def _should_apply_stage_update(current_stage: Optional[int], new_stage: Optional[int]) -> bool:
    """防止券商对账将已经推进的 post-trade 阶段回退。"""
    if new_stage is None:
        return False
    if current_stage is None:
        return True
    if current_stage >= _POST_TRADE_STAGE_START and new_stage < current_stage:
        return False
    return new_stage != current_stage


def _extract_live_position_symbols(raw_positions: list[Any]) -> set[str]:
    """从券商持仓列表中提取当前真实持仓 symbol 集合。"""
    symbols: set[str] = set()
    for pos in raw_positions:
        if isinstance(pos, dict):
            symbol = pos.get("symbol") or pos.get("ticker")
            qty = pos.get("quantity") or pos.get("qty") or 0
        else:
            symbol = getattr(pos, "symbol", None) or getattr(pos, "ticker", None)
            qty = getattr(pos, "quantity", None) or getattr(pos, "qty", None) or 0

        try:
            qty_val = float(qty or 0)
        except (TypeError, ValueError):
            qty_val = 0.0

        if symbol and abs(qty_val) > 0:
            symbols.add(str(symbol))
    return symbols


def _derive_reconciled_stage(signal: TradingSignal, live_position_symbols: set[str]) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """根据最新信号状态与真实持仓推导计划阶段。"""
    if signal.status == SignalStatus.EXECUTED:
        if signal.symbol in live_position_symbols:
            return 9, "EXECUTED", "HELD"
        return 12, "EXECUTED", "CLOSED"
    if signal.status == SignalStatus.CANCELLED:
        return 16, "REVOKED", "CLOSED"
    if signal.status == SignalStatus.REJECTED:
        return 16, "FAILED", "CLOSED"
    return None, None, None


def _normalize_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _reason_implies_failed(reason: str | None) -> bool:
    text = str(reason or "").lower()
    if not text:
        return False
    keywords = (
        "failed",
        "reject",
        "rejected",
        "refused",
        "insufficient",
        "expired",
        "exceeds your current holdings",
        "券商拒绝",
        "可用资金不足",
        "失败",
        "拒绝",
        "过期",
    )
    return any(keyword in text for keyword in keywords)


def _classify_terminal_status(reason: str | None) -> str:
    text = str(reason or "").lower()
    if not text:
        return "REVOKED"
    if "expired" in text or "过期" in text:
        return "EXPIRED"
    if "cancel" in text or "撤" in text:
        return "REVOKED"
    if _reason_implies_failed(reason):
        return "FAILED"
    return "REVOKED"


async def _find_plan_signal(session: AsyncSession, real_account_id: str, plan: Any) -> TradingSignal | None:
    plan_tags = cast(dict[str, Any], getattr(plan, "plan_tags", None) or {}) if isinstance(getattr(plan, "plan_tags", None), dict) else {}
    snapshot = cast(dict[str, Any], getattr(plan, "provenance_snapshot", None) or {}) if isinstance(getattr(plan, "provenance_snapshot", None), dict) else {}
    raw_exec_ref = snapshot.get("execution_ref")
    exec_ref = cast(dict[str, Any], raw_exec_ref or {}) if isinstance(raw_exec_ref, dict) else {}

    signal_db_id = plan_tags.get("signal_db_id") or exec_ref.get("signal_db_id")
    if signal_db_id:
        sig = (
            await session.execute(select(TradingSignal).where(TradingSignal.id == int(signal_db_id)).limit(1))
        ).scalar_one_or_none()
        if sig is not None:
            return sig

    signal_id = plan_tags.get("signal_id") or exec_ref.get("signal_id")
    if signal_id:
        sig = (
            await session.execute(select(TradingSignal).where(TradingSignal.signal_id == str(signal_id)).limit(1))
        ).scalar_one_or_none()
        if sig is not None:
            return sig

    order_id = plan_tags.get("order_id") or exec_ref.get("order_id")
    if order_id:
        sig = (
            await session.execute(select(TradingSignal).where(TradingSignal.order_id == str(order_id)).limit(1))
        ).scalar_one_or_none()
        if sig is not None:
            return sig

    plan_created_at = _normalize_utc(getattr(plan, "created_at", None))
    if plan_created_at is None:
        return None
    window_start = plan_created_at - timedelta(minutes=15)
    window_end = plan_created_at + timedelta(minutes=15)
    return (
        await session.execute(
            select(TradingSignal)
            .where(TradingSignal.account_id == real_account_id)
            .where(TradingSignal.symbol == plan.symbol)
            .where(TradingSignal.created_at >= window_start.replace(tzinfo=None))
            .where(TradingSignal.created_at <= window_end.replace(tzinfo=None))
            .order_by(desc(TradingSignal.created_at), desc(TradingSignal.id))
            .limit(1)
        )
    ).scalar_one_or_none()


async def _find_plan_intent_and_audit(session: AsyncSession, real_account_id: str, plan: Any) -> tuple[AutonomousExecutionIntent | None, AutonomyAuditLog | None]:
    plan_created_at = _normalize_utc(getattr(plan, "created_at", None)) or datetime.now(timezone.utc)
    window_start = plan_created_at - timedelta(minutes=15)
    window_end = plan_created_at + timedelta(minutes=15)

    intent = (
        await session.execute(
            select(AutonomousExecutionIntent)
            .where(AutonomousExecutionIntent.account_id == real_account_id)
            .where(AutonomousExecutionIntent.symbol == plan.symbol)
            .where(AutonomousExecutionIntent.created_at >= window_start.replace(tzinfo=None))
            .where(AutonomousExecutionIntent.created_at <= window_end.replace(tzinfo=None))
            .order_by(desc(AutonomousExecutionIntent.created_at), desc(AutonomousExecutionIntent.id))
            .limit(1)
        )
    ).scalar_one_or_none()

    audit = (
        await session.execute(
            select(AutonomyAuditLog)
            .where(AutonomyAuditLog.account_id == real_account_id)
            .where(AutonomyAuditLog.symbol == plan.symbol)
            .where(AutonomyAuditLog.created_at >= window_start.replace(tzinfo=None))
            .where(AutonomyAuditLog.created_at <= window_end.replace(tzinfo=None))
            .order_by(desc(AutonomyAuditLog.created_at), desc(AutonomyAuditLog.id))
            .limit(1)
        )
    ).scalar_one_or_none()
    return intent, audit


async def _derive_plan_resolution(
    session: AsyncSession,
    real_account_id: str,
    plan: Any,
    live_position_symbols: set[str],
) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    signal = await _find_plan_signal(session, real_account_id, plan)
    if signal is not None:
        stage, status, position_state = _derive_reconciled_stage(signal, live_position_symbols)
        if stage is not None:
            return stage, status, position_state, f"signal:{signal.status.value}"

    intent, audit = await _find_plan_intent_and_audit(session, real_account_id, plan)
    audit_revoked = audit is not None and audit.revoked_at is not None
    intent_failed = intent is not None and str(intent.status or "").upper() == "FAILED"

    if audit_revoked or intent_failed:
        audit_reason = audit.revoke_reason if audit is not None and audit_revoked else None
        intent_reason = intent.reason if intent is not None and intent_failed else None
        reason = audit_reason or intent_reason
        return 16, _classify_terminal_status(reason), "CLOSED", reason

    if plan.symbol in live_position_symbols:
        return 9, "EXECUTED", "HELD", "live-position"

    stage_entered_at = _normalize_utc(getattr(plan, "stage_entered_at", None))
    if (
        str(getattr(plan, "plan_status", "") or "").upper() == "EXECUTED"
        and stage_entered_at is not None
        and datetime.now(timezone.utc) - stage_entered_at >= _STAGE7_STALE_CLOSE_AFTER
    ):
        return 12, "EXECUTED", "CLOSED", "stale-executed-no-position"

    return None, None, None, None


async def _close_stale_closing_positions(
    session: AsyncSession,
    account_id: str,
    live_position_symbols: set[str],
) -> int:
    """兜底收口：券商已无持仓但 Position 仍卡在 CLOSING 时，自动推进到 CLOSED。"""
    rows = (
        await session.execute(
            select(Position)
            .where(
                Position.account_id == account_id,
                Position.status == PositionStatus.CLOSING.value,
                Position.open_qty > 0,
            )
            .order_by(desc(Position.updated_at), desc(Position.id))
        )
    ).scalars().all()

    closed = 0
    plm = PositionLifecycleManager(session)
    for pos in rows:
        if pos.symbol in live_position_symbols:
            continue

        slice_row = (
            await session.execute(
                select(ExecutionSlice)
                .where(
                    ExecutionSlice.position_id == pos.id,
                    ExecutionSlice.action.in_([
                        SliceAction.REDUCE.value,
                        SliceAction.CLOSE.value,
                    ]),
                    ExecutionSlice.status.in_([
                        SliceStatus.PENDING.value,
                        SliceStatus.SUBMITTED.value,
                        SliceStatus.PARTIALLY_FILLED.value,
                    ]),
                )
                .order_by(desc(ExecutionSlice.updated_at), desc(ExecutionSlice.id))
                .limit(1)
            )
        ).scalars().first()
        if slice_row is None:
            continue

        remaining_qty = float(pos.open_qty or slice_row.requested_qty or 0.0)
        if remaining_qty <= 0:
            continue

        avg_price = float(
            pos.avg_close_price
            or slice_row.avg_fill_price
            or pos.avg_entry_price
            or 0.0
        )
        await plm.on_slice_filled(
            slice_id=slice_row.id,
            filled_qty=remaining_qty,
            avg_price=avg_price,
            partial=False,
        )
        closed += 1

    return closed


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
        .where(TradingSignal.created_at >= since)
    )

    raw_candidate_ids = {
        str(r[0]) for r in audit_order_rows.fetchall() if r and r[0]
    } | {
        str(r[0]) for r in signal_order_rows.fetchall() if r and r[0]
    }

    candidate_ids = {oid for oid in raw_candidate_ids if _is_broker_native_order_id(oid)}
    skipped_local_only = len(raw_candidate_ids) - len(candidate_ids)
    if skipped_local_only > 0:
        logger.debug(
            "[BrokerSync] skipped %d local/non-broker order ids during reconcile candidate build",
            skipped_local_only,
        )

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
    from app.models.trading_plan import TradingPlan
    from app.models.fsm_transition_log import FsmTransitionLog

    try:
        raw_positions = await broker.list_underlying_positions(real_account_id)
    except Exception:
        raw_positions = []
    live_position_symbols = _extract_live_position_symbols(list(raw_positions or []))

    positions_force_closed = await _close_stale_closing_positions(
        session,
        real_account_id,
        live_position_symbols,
    )

    plan_reconciled = 0

    # 只处理仍在下单/执行链路中的计划；S12+ 由 post-trade pipeline 负责推进。
    plans_res = await session.execute(
        select(TradingPlan).where(TradingPlan.account_id == real_account_id)
    )
    for plan in plans_res.scalars().all():
        if not _is_plan_reconcile_candidate(plan.pipeline_stage, plan.plan_status):
            continue

        new_stage, new_status, new_position_fsm_state, resolution_reason = await _derive_plan_resolution(
            session,
            real_account_id,
            plan,
            live_position_symbols,
        )

        should_update_stage = _should_apply_stage_update(plan.pipeline_stage, new_stage)
        should_update_status = new_status is not None and new_status != plan.plan_status
        should_update_position_fsm = (
            new_position_fsm_state is not None and new_position_fsm_state != plan.position_fsm_state
        )

        if should_update_stage or should_update_status or should_update_position_fsm:
            old_stage = plan.pipeline_stage
            old_position_fsm = plan.position_fsm_state
            applied_stage: Optional[int] = None
            if should_update_stage and new_stage is not None:
                applied_stage = new_stage
                plan.pipeline_stage = applied_stage
                plan.stage_entered_at = datetime.now(timezone.utc)
            if new_position_fsm_state is not None:
                plan.position_fsm_state = new_position_fsm_state
            if new_status:
                plan.plan_status = new_status
            plan_reconciled += 1

            if applied_stage is not None:
                session.add(FsmTransitionLog(
                    plan_id=plan.id,
                    fsm_type="PLAN",
                    from_state=f"STAGE_{old_stage}" if old_stage is not None else "UNKNOWN",
                    to_state=f"STAGE_{applied_stage}",
                    trigger_reason=(
                        f"Broker status sync (Manual Cancel/Fill Sync): {resolution_reason}"
                        if resolution_reason
                        else "Broker status sync (Manual Cancel/Fill Sync)"
                    ),
                ))
            if should_update_position_fsm and new_position_fsm_state is not None:
                await lifecycle_service.append_position_fsm_log(
                    session,
                    plan_id=plan.id,
                    from_state=old_position_fsm,
                    to_state=new_position_fsm_state,
                    engine="broker_sync",
                    trigger_reason=(
                        f"Broker status sync (Manual Cancel/Fill Sync): {resolution_reason}"
                        if resolution_reason
                        else "Broker status sync (Manual Cancel/Fill Sync)"
                    ),
                )

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
        "positions_force_closed": positions_force_closed,
        "plans_reconciled": plan_reconciled,
        "orphan_signals_fixed": orphan_fixed,
        "journal_entries_created": journal_created,
        "remaining_EXECUTING": int(remaining_exec),
        "signals_with_order_id": int(with_order_id),
        "audit_revoked_marked": int(revoked_marked),
    }
