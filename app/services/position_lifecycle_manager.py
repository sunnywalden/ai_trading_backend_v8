"""V10.4.4: PositionLifecycleManager

统一管理 Position 聚合根的状态迁移、ExecutionSlice 创建、
PositionLifecycleEvent 写入以及 EventBus 事件发布。

外部代码（autonomous_engine、position_monitor、order_executor 等）
通过本服务操作 Position，禁止直接修改 Position.status 字段。

使用示例::

    async with get_session_ctx() as session:
        mgr = PositionLifecycleManager(session)

        # 开仓意图 → 创建 Position + ExecutionSlice(OPEN)
        pos, slc = await mgr.open_position(
            account_id="ACC-1", symbol="AAPL",
            requested_qty=100, signal_id="sig-xxx",
        )

        # 切片成交回调 → 更新 Position 状态
        await mgr.on_slice_filled(slice_id=slc.id, filled_qty=100, avg_price=175.0)

        # 平仓意图 → 创建 ExecutionSlice(CLOSE)
        slc2 = await mgr.close_position(
            position_id=pos.id,
            requested_qty=100,
            closing_reason=ClosingReason.STOP_LOSS,
        )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import Topics, event_bus
from app.models.execution_slice import ExecutionSlice, SliceAction, SliceStatus
from app.models.position import ClosingReason, ExecutionPath, Position, PositionStatus
from app.models.position_lifecycle_event import EventKind, PositionLifecycleEvent
from app.services.portfolio_cache_service import invalidate_portfolio_view_caches

logger = logging.getLogger(__name__)

# 允许从 ACTIVE 发起加仓的状态集合
_SCALABLE_STATUSES = {
    PositionStatus.ACTIVE.value,
    PositionStatus.SCALING_IN.value,
    PositionStatus.PARTIALLY_CLOSED.value,
}
# 允许从 ACTIVE 发起平仓的状态集合
_CLOSEABLE_STATUSES = {
    PositionStatus.ACTIVE.value,
    PositionStatus.SCALING_IN.value,
    PositionStatus.SCALING_OUT.value,
    PositionStatus.PARTIALLY_CLOSED.value,
    PositionStatus.EXCEPTION.value,
}


class PositionLifecycleManager:
    """Position 生命周期管理器（每次请求创建一个实例，绑定同一 AsyncSession）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 开仓
    # ─────────────────────────────────────────────────────────────────────────

    async def open_position(
        self,
        account_id: str,
        symbol: str,
        requested_qty: float,
        direction: str = "LONG",
        thesis_key: str = "default",
        signal_id: Optional[str] = None,
        signal_db_id: Optional[int] = None,
        intent_id: Optional[str] = None,
        execution_path: str = ExecutionPath.AUTONOMOUS.value,
        autonomy_level: str = "SEMI",
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        max_holding_days: Optional[int] = None,
        plan_id: Optional[int] = None,
        order_id: Optional[str] = None,
    ) -> Tuple[Position, ExecutionSlice]:
        """创建新 Position（PENDING）并生成 OPEN ExecutionSlice。

        如果 (account_id, symbol, thesis_key) 已存在活跃 Position，
        则自动路由到 add_to_position（避免意外重复开仓）。
        """
        existing = await self._find_active_position(account_id, symbol, thesis_key)
        if existing:
            logger.info(
                "[PLM] Position already exists for %s/%s/%s (id=%d), routing to add",
                account_id,
                symbol,
                thesis_key,
                existing.id,
            )
            slc = await self.add_to_position(
                position_id=existing.id,
                requested_qty=requested_qty,
                signal_id=signal_id,
                signal_db_id=signal_db_id,
                intent_id=intent_id,
                execution_path=execution_path,
                autonomy_level=autonomy_level,
            )
            return existing, slc

        pos = Position(
            account_id=account_id,
            symbol=symbol,
            thesis_key=thesis_key,
            status=PositionStatus.PENDING.value,
            direction=direction,
            initial_signal_uid=signal_id,
            initial_signal_id=signal_db_id,
            latest_plan_id=plan_id,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            max_holding_days=max_holding_days,
        )
        self._session.add(pos)
        await self._session.flush()  # 获取 pos.id

        slc = ExecutionSlice(
            position_id=pos.id,
            account_id=account_id,
            symbol=symbol,
            action=SliceAction.OPEN.value,
            status=(
                SliceStatus.SUBMITTED.value if order_id else SliceStatus.PENDING.value
            ),
            requested_qty=requested_qty,
            submitted_qty=requested_qty if order_id else None,
            order_ids=[order_id] if order_id else None,
            signal_id=signal_id,
            signal_db_id=signal_db_id,
            intent_id=intent_id,
            execution_path=execution_path,
            autonomy_level=autonomy_level,
        )
        self._session.add(slc)
        await self._session.flush()

        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=EventKind.STATE_TRANSITION,
            from_status=None,
            to_status=PositionStatus.PENDING.value,
            summary=f"仓位创建 {symbol} 方向={direction} qty={requested_qty}",
            actor="system",
            signal_id=signal_id,
            intent_id=intent_id,
            meta={"execution_path": execution_path, "autonomy_level": autonomy_level},
        )
        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=EventKind.SLICE_CREATED,
            summary=f"OPEN 切片创建 qty={requested_qty}",
            actor="system",
            meta={"action": SliceAction.OPEN.value, "requested_qty": requested_qty},
        )

        await self._emit(
            Topics.SLICE_CREATED,
            {
                "slice_id": slc.id,
                "position_id": pos.id,
                "action": SliceAction.OPEN.value,
                "qty": requested_qty,
                "symbol": symbol,
                "account_id": account_id,
            },
        )

        await self._commit_and_invalidate(pos.account_id)
        logger.info(
            "[PLM] Created Position %d + OPEN Slice %d for %s/%s",
            pos.id,
            slc.id,
            account_id,
            symbol,
        )
        return pos, slc

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 加仓
    # ─────────────────────────────────────────────────────────────────────────

    async def add_to_position(
        self,
        position_id: int,
        requested_qty: float,
        signal_id: Optional[str] = None,
        signal_db_id: Optional[int] = None,
        intent_id: Optional[str] = None,
        execution_path: str = ExecutionPath.AUTONOMOUS.value,
        autonomy_level: str = "SEMI",
        order_id: Optional[str] = None,
    ) -> ExecutionSlice:
        """在已有 Position 上发起加仓切片（ADD）。"""
        pos = await self._require_position(position_id)
        if pos.status not in _SCALABLE_STATUSES:
            raise ValueError(
                f"Position {position_id} status={pos.status} cannot accept ADD slice"
            )

        slc = ExecutionSlice(
            position_id=pos.id,
            account_id=pos.account_id,
            symbol=pos.symbol,
            action=SliceAction.ADD.value,
            status=(
                SliceStatus.SUBMITTED.value if order_id else SliceStatus.PENDING.value
            ),
            requested_qty=requested_qty,
            submitted_qty=requested_qty if order_id else None,
            order_ids=[order_id] if order_id else None,
            signal_id=signal_id,
            signal_db_id=signal_db_id,
            intent_id=intent_id,
            execution_path=execution_path,
            autonomy_level=autonomy_level,
        )
        self._session.add(slc)

        prev_status = pos.status
        pos.status = PositionStatus.SCALING_IN.value
        pos.last_action_at = _utcnow()
        await self._session.flush()

        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=EventKind.SLICE_CREATED,
            summary=f"ADD 切片创建 qty={requested_qty}",
            actor="system",
            meta={"action": SliceAction.ADD.value, "requested_qty": requested_qty},
        )
        if prev_status != pos.status:
            await self._log_state_transition(
                pos,
                prev_status,
                PositionStatus.SCALING_IN.value,
                actor="system",
                slice_id=slc.id,
            )

        await self._emit(
            Topics.SLICE_CREATED,
            {
                "slice_id": slc.id,
                "position_id": pos.id,
                "action": SliceAction.ADD.value,
                "qty": requested_qty,
            },
        )
        await self._commit_and_invalidate(pos.account_id)
        return slc

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 减仓 / 平仓
    # ─────────────────────────────────────────────────────────────────────────

    async def reduce_position(
        self,
        position_id: int,
        requested_qty: float,
        closing_reason: str = ClosingReason.VOLITIONAL.value,
        signal_id: Optional[str] = None,
        signal_db_id: Optional[int] = None,
        intent_id: Optional[str] = None,
        execution_path: str = ExecutionPath.AUTONOMOUS.value,
        autonomy_level: str = "SEMI",
        exemption_applied: bool = False,
        exemption_detail: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> ExecutionSlice:
        """减仓或平仓——自动判断 requested_qty 是否为全仓。"""
        pos = await self._require_position(position_id)
        if pos.status not in _CLOSEABLE_STATUSES:
            raise ValueError(
                f"Position {position_id} status={pos.status} cannot accept REDUCE/CLOSE slice"
            )

        # 自动判断是全仓平仓还是部分平仓
        is_full_close = requested_qty >= pos.open_qty > 0
        action = SliceAction.CLOSE.value if is_full_close else SliceAction.REDUCE.value

        slc = ExecutionSlice(
            position_id=pos.id,
            account_id=pos.account_id,
            symbol=pos.symbol,
            action=action,
            status=(
                SliceStatus.SUBMITTED.value if order_id else SliceStatus.PENDING.value
            ),
            requested_qty=requested_qty,
            submitted_qty=requested_qty if order_id else None,
            order_ids=[order_id] if order_id else None,
            closing_reason=closing_reason,
            signal_id=signal_id,
            signal_db_id=signal_db_id,
            intent_id=intent_id,
            execution_path=execution_path,
            autonomy_level=autonomy_level,
            exemption_applied=exemption_applied,
            exemption_detail=exemption_detail,
        )
        self._session.add(slc)

        prev_status = pos.status
        pos.status = PositionStatus.CLOSING.value
        pos.closing_reason = closing_reason
        pos.closing_source = execution_path
        pos.last_action_at = _utcnow()
        await self._session.flush()

        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=EventKind.SLICE_CREATED,
            summary=f"{action} 切片创建 qty={requested_qty} reason={closing_reason}",
            actor="system",
            meta={
                "action": action,
                "requested_qty": requested_qty,
                "closing_reason": closing_reason,
                "exemption_applied": exemption_applied,
            },
        )
        if prev_status != pos.status:
            await self._log_state_transition(
                pos,
                prev_status,
                PositionStatus.CLOSING.value,
                actor="system",
                slice_id=slc.id,
            )

        await self._emit(
            Topics.SLICE_CREATED,
            {
                "slice_id": slc.id,
                "position_id": pos.id,
                "action": action,
                "qty": requested_qty,
                "closing_reason": closing_reason,
            },
        )
        await self._commit_and_invalidate(pos.account_id)
        return slc

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 切片成交回调
    # ─────────────────────────────────────────────────────────────────────────

    async def on_slice_filled(
        self,
        slice_id: int,
        filled_qty: float,
        avg_price: float,
        partial: bool = False,
    ) -> Position:
        """order_executor 成交后回调本方法，更新 ExecutionSlice + Position。"""
        slc = await self._require_slice(slice_id)
        pos = await self._require_position(slc.position_id)

        # 更新切片
        slc.filled_qty = filled_qty
        slc.avg_fill_price = avg_price
        slc.status = (
            SliceStatus.PARTIALLY_FILLED.value if partial else SliceStatus.FILLED.value
        )
        slc.filled_at = _utcnow() if not partial else slc.filled_at

        prev_status = pos.status

        if slc.action == SliceAction.OPEN.value:
            pos.filled_qty = (pos.filled_qty or 0) + filled_qty
            pos.open_qty = pos.filled_qty - (pos.closed_qty or 0)
            pos.avg_entry_price = avg_price  # 简化：首次开仓直接赋值
            if not pos.opened_at:
                pos.opened_at = _utcnow()
            if not partial:
                pos.status = PositionStatus.ACTIVE.value
                await self._emit(
                    Topics.POSITION_OPENED,
                    {
                        "position_id": pos.id,
                        "symbol": pos.symbol,
                        "account_id": pos.account_id,
                        "qty": filled_qty,
                        "avg_price": avg_price,
                    },
                )

        elif slc.action == SliceAction.ADD.value:
            pos.filled_qty = (pos.filled_qty or 0) + filled_qty
            pos.open_qty = pos.filled_qty - (pos.closed_qty or 0)
            # 更新均价（加权平均）
            old_qty = pos.open_qty - filled_qty
            if old_qty > 0 and pos.avg_entry_price:
                pos.avg_entry_price = (
                    pos.avg_entry_price * old_qty + avg_price * filled_qty
                ) / pos.open_qty
            if not partial:
                pos.status = PositionStatus.ACTIVE.value
                await self._emit(
                    Topics.POSITION_ADDED,
                    {
                        "position_id": pos.id,
                        "symbol": pos.symbol,
                        "added_qty": filled_qty,
                        "new_total_qty": pos.open_qty,
                    },
                )

        elif slc.action in (SliceAction.REDUCE.value, SliceAction.CLOSE.value):
            pos.closed_qty = (pos.closed_qty or 0) + filled_qty
            pos.open_qty = max(0, (pos.open_qty or 0) - filled_qty)
            if pos.avg_entry_price:
                pos.realized_pnl = (pos.realized_pnl or 0) + (
                    avg_price - pos.avg_entry_price
                ) * filled_qty
            pos.avg_close_price = avg_price
            if not partial and pos.open_qty <= 0:
                pos.status = PositionStatus.CLOSED.value
                pos.closed_at = _utcnow()
                await self._emit(
                    Topics.POSITION_CLOSED,
                    {
                        "position_id": pos.id,
                        "symbol": pos.symbol,
                        "closing_reason": slc.closing_reason or pos.closing_reason,
                        "realized_pnl": pos.realized_pnl,
                    },
                )
            elif not partial and pos.open_qty > 0:
                pos.status = PositionStatus.PARTIALLY_CLOSED.value
                await self._emit(
                    Topics.POSITION_REDUCED,
                    {
                        "position_id": pos.id,
                        "symbol": pos.symbol,
                        "reduced_qty": filled_qty,
                        "remaining_qty": pos.open_qty,
                        "closing_reason": slc.closing_reason,
                    },
                )

        pos.last_action_at = _utcnow()

        event_kind = (
            EventKind.SLICE_PARTIALLY_FILLED if partial else EventKind.SLICE_FILLED
        )
        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=event_kind,
            from_status=prev_status,
            to_status=pos.status,
            summary=(
                f"切片{'部分' if partial else '全部'}成交 "
                f"qty={filled_qty} @ {avg_price:.4f}"
            ),
            actor="order_executor",
            meta={
                "filled_qty": filled_qty,
                "avg_price": avg_price,
                "open_qty": pos.open_qty,
                "realized_pnl": pos.realized_pnl,
            },
        )
        if prev_status != pos.status:
            await self._log_state_transition(
                pos,
                prev_status,
                pos.status,
                actor="order_executor",
                slice_id=slc.id,
            )

        await self._emit(
            Topics.SLICE_FILLED,
            {
                "slice_id": slc.id,
                "position_id": pos.id,
                "filled_qty": filled_qty,
                "avg_price": avg_price,
            },
        )

        await self._commit_and_invalidate(pos.account_id)
        return pos

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 切片失败 / 卡住
    # ─────────────────────────────────────────────────────────────────────────

    async def on_slice_failed(
        self,
        slice_id: int,
        error_message: str,
        actor: str = "order_executor",
    ) -> Position:
        slc = await self._require_slice(slice_id)
        pos = await self._require_position(slc.position_id)

        slc.status = SliceStatus.FAILED.value
        slc.error_message = error_message

        # 如果 Position 还处于 OPENING / CLOSING，且没有其他 Active 切片，推入 EXCEPTION
        active_slices = await self._count_active_slices(
            pos.id, exclude_slice_id=slice_id
        )
        prev_status = pos.status
        if active_slices == 0:
            if pos.status in (
                PositionStatus.PENDING.value,
                PositionStatus.OPENING.value,
            ):
                pos.status = PositionStatus.EXCEPTION.value
            elif pos.status == PositionStatus.CLOSING.value:
                pos.status = PositionStatus.EXCEPTION.value

        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=EventKind.SLICE_FAILED,
            from_status=prev_status,
            to_status=pos.status,
            summary=f"切片执行失败: {error_message[:120]}",
            actor=actor,
            meta={"error": error_message},
        )
        if prev_status != pos.status:
            await self._log_state_transition(
                pos,
                prev_status,
                pos.status,
                actor=actor,
                slice_id=slc.id,
            )
            if pos.status == PositionStatus.EXCEPTION.value:
                await self._emit(
                    Topics.POSITION_EXCEPTION,
                    {
                        "position_id": pos.id,
                        "symbol": pos.symbol,
                        "exception_detail": error_message,
                    },
                )

        await self._emit(
            Topics.SLICE_FAILED,
            {
                "slice_id": slc.id,
                "position_id": pos.id,
                "error": error_message,
            },
        )
        await self._commit_and_invalidate(pos.account_id)
        return pos

    async def on_slice_stuck(
        self,
        slice_id: int,
        elapsed_seconds: float,
    ) -> Position:
        slc = await self._require_slice(slice_id)
        pos = await self._require_position(slc.position_id)

        slc.status = SliceStatus.STUCK.value
        slc.stuck_at = _utcnow()

        prev_status = pos.status
        pos.status = PositionStatus.EXCEPTION.value

        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=EventKind.SLICE_STUCK,
            from_status=prev_status,
            to_status=PositionStatus.EXCEPTION.value,
            summary=f"切片卡住 {elapsed_seconds:.0f}s 无成交回报",
            actor="autonomy_health_monitor",
            meta={"elapsed_seconds": elapsed_seconds},
        )
        if prev_status != PositionStatus.EXCEPTION.value:
            await self._log_state_transition(
                pos,
                prev_status,
                PositionStatus.EXCEPTION.value,
                actor="autonomy_health_monitor",
                slice_id=slc.id,
            )
            await self._emit(
                Topics.POSITION_EXCEPTION,
                {
                    "position_id": pos.id,
                    "symbol": pos.symbol,
                    "exception_detail": f"Slice {slice_id} stuck {elapsed_seconds:.0f}s",
                },
            )
        await self._emit(
            Topics.SLICE_STUCK,
            {
                "slice_id": slc.id,
                "position_id": pos.id,
                "symbol": pos.symbol,
                "elapsed_seconds": elapsed_seconds,
            },
        )
        await self._commit_and_invalidate(pos.account_id)
        return pos

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 人工强制平仓
    # ─────────────────────────────────────────────────────────────────────────

    async def manual_close(
        self,
        position_id: int,
        actor: str,
        note: Optional[str] = None,
    ) -> ExecutionSlice:
        """人工强制平仓——直接全量创建 CLOSE 切片，标记 MANUAL_OVERRIDE。"""
        pos = await self._require_position(position_id)
        if pos.status in (PositionStatus.CLOSED.value, PositionStatus.LIQUIDATED.value):
            raise ValueError(f"Position {position_id} is already {pos.status}")

        slc = await self.reduce_position(
            position_id=position_id,
            requested_qty=pos.open_qty or 1.0,
            closing_reason=ClosingReason.MANUAL_OVERRIDE.value,
            execution_path=ExecutionPath.MANUAL.value,
            autonomy_level="MANUAL",
        )

        pos.closing_note = note
        await self._log_event(
            position_id=pos.id,
            slice_id=slc.id,
            kind=EventKind.MANUAL_CLOSE,
            summary=f"人工强制平仓 by {actor}",
            actor=actor,
            meta={"note": note},
        )
        await self._commit_and_invalidate(pos.account_id)
        return slc

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 强制清算
    # ─────────────────────────────────────────────────────────────────────────

    async def liquidate(
        self,
        position_id: int,
        reason: str,
        actor: str = "risk_gate",
    ) -> Position:
        """风控 / 熔断强制清算（直接推到 LIQUIDATED 状态，不等切片回调）。"""
        pos = await self._require_position(position_id)
        prev_status = pos.status
        pos.status = PositionStatus.LIQUIDATED.value
        pos.closing_reason = ClosingReason.CIRCUIT_BREAKER.value
        pos.closing_source = ExecutionPath.AUTONOMOUS.value
        pos.closed_at = _utcnow()
        pos.closing_note = reason

        await self._log_state_transition(
            pos,
            prev_status,
            PositionStatus.LIQUIDATED.value,
            actor=actor,
        )
        await self._log_event(
            position_id=pos.id,
            kind=EventKind.CIRCUIT_BREAKER,
            summary=f"强制清算: {reason}",
            actor=actor,
        )
        await self._emit(
            Topics.POSITION_LIQUIDATED,
            {
                "position_id": pos.id,
                "symbol": pos.symbol,
                "reason": reason,
            },
        )
        await self._commit_and_invalidate(pos.account_id)
        return pos

    # ─────────────────────────────────────────────────────────────────────────
    # 公共接口 — 豁免标记
    # ─────────────────────────────────────────────────────────────────────────

    async def grant_exemption(
        self,
        position_id: int,
        reason: str,
        actor: str = "risk_gate",
    ) -> Position:
        pos = await self._require_position(position_id)
        pos.exemption_active = True
        pos.exemption_reason = reason
        await self._log_event(
            position_id=pos.id,
            kind=EventKind.EXEMPTION_GRANTED,
            summary=f"豁免授予: {reason}",
            actor=actor,
            meta={"reason": reason},
        )
        await self._session.commit()
        return pos

    async def revoke_exemption(
        self,
        position_id: int,
        reason: str = "",
        actor: str = "risk_gate",
    ) -> Position:
        pos = await self._require_position(position_id)
        pos.exemption_active = False
        pos.exemption_reason = None
        await self._log_event(
            position_id=pos.id,
            kind=EventKind.EXEMPTION_REVOKED,
            summary=f"豁免撤销: {reason}",
            actor=actor,
        )
        await self._session.commit()
        return pos

    # ─────────────────────────────────────────────────────────────────────────
    # 内部工具
    # ─────────────────────────────────────────────────────────────────────────

    async def _find_active_position(
        self,
        account_id: str,
        symbol: str,
        thesis_key: str,
    ) -> Optional[Position]:
        result = await self._session.execute(
            select(Position).where(
                Position.account_id == account_id,
                Position.symbol == symbol,
                Position.thesis_key == thesis_key,
                Position.status.notin_(
                    [
                        PositionStatus.CLOSED.value,
                        PositionStatus.LIQUIDATED.value,
                    ]
                ),
            )
        )
        return result.scalars().first()

    async def _require_position(self, position_id: int) -> Position:
        result = await self._session.execute(
            select(Position).where(Position.id == position_id)
        )
        pos = result.scalars().first()
        if not pos:
            raise ValueError(f"Position {position_id} not found")
        return pos

    async def _require_slice(self, slice_id: int) -> ExecutionSlice:
        result = await self._session.execute(
            select(ExecutionSlice).where(ExecutionSlice.id == slice_id)
        )
        slc = result.scalars().first()
        if not slc:
            raise ValueError(f"ExecutionSlice {slice_id} not found")
        return slc

    async def _count_active_slices(
        self,
        position_id: int,
        exclude_slice_id: Optional[int] = None,
    ) -> int:
        from sqlalchemy import func as sqlfunc

        stmt = (
            select(sqlfunc.count())
            .select_from(ExecutionSlice)
            .where(
                ExecutionSlice.position_id == position_id,
                ExecutionSlice.status.in_(
                    [
                        SliceStatus.PENDING.value,
                        SliceStatus.SUBMITTED.value,
                        SliceStatus.PARTIALLY_FILLED.value,
                    ]
                ),
            )
        )
        if exclude_slice_id is not None:
            stmt = stmt.where(ExecutionSlice.id != exclude_slice_id)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def _log_state_transition(
        self,
        pos: Position,
        from_status: Optional[str],
        to_status: str,
        actor: str,
        slice_id: Optional[int] = None,
    ) -> None:
        await self._log_event(
            position_id=pos.id,
            slice_id=slice_id,
            kind=EventKind.STATE_TRANSITION,
            from_status=from_status,
            to_status=to_status,
            summary=f"状态迁移 {from_status} → {to_status}",
            actor=actor,
        )

    async def _log_event(
        self,
        position_id: int,
        kind: EventKind,
        summary: str,
        slice_id: Optional[int] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        actor: str = "system",
        signal_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        detail: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        event = PositionLifecycleEvent(
            position_id=position_id,
            slice_id=slice_id,
            kind=kind.value,
            summary=summary,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            signal_id=signal_id,
            intent_id=intent_id,
            detail=detail,
            metadata_json=meta,
            occurred_at=_utcnow(),
        )
        self._session.add(event)
        await self._session.flush()

    async def _commit_and_invalidate(self, account_id: Optional[str]) -> None:
        await self._session.commit()
        if account_id:
            await invalidate_portfolio_view_caches(str(account_id))

    @staticmethod
    async def _emit(topic: Topics, payload: dict) -> None:
        try:
            await event_bus.publish(topic, payload)
        except Exception as exc:
            logger.warning("[PLM] EventBus publish failed topic=%s: %s", topic, exc)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
