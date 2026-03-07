"""V10.4.4 – Position query service.

Read-only queries for Position aggregate, ExecutionSlice, and
PositionLifecycleEvent.  All methods return plain dicts / lists
so routers can serialise them without importing SQLAlchemy models.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.execution_slice import ExecutionSlice, SliceStatus
from app.models.position import Position, PositionStatus
from app.models.position_lifecycle_event import PositionLifecycleEvent

# ---------------------------------------------------------------------------
# Statuses considered "active" (position is not yet fully settled)
# ---------------------------------------------------------------------------
_ACTIVE_STATUSES = {
    PositionStatus.PENDING.value,
    PositionStatus.OPENING.value,
    PositionStatus.ACTIVE.value,
    PositionStatus.SCALING_IN.value,
    PositionStatus.SCALING_OUT.value,
    PositionStatus.CLOSING.value,
    PositionStatus.PARTIALLY_CLOSED.value,
    PositionStatus.EXCEPTION.value,
}


class PositionQueryService:
    """Provides read-only views over Position-centric data."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Active positions
    # ------------------------------------------------------------------

    async def get_active_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Return all non-final positions for an account."""
        stmt = (
            select(Position)
            .where(
                Position.account_id == account_id,
                Position.status.in_(list(_ACTIVE_STATUSES)),
            )
            .order_by(Position.opened_at.desc().nullslast())
        )
        result = await self._db.execute(stmt)
        rows = result.scalars().all()
        return [_pos_to_dict(p) for p in rows]

    async def get_exception_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Return positions in EXCEPTION status."""
        stmt = (
            select(Position)
            .where(
                Position.account_id == account_id,
                Position.status == PositionStatus.EXCEPTION.value,
            )
            .order_by(Position.last_action_at.desc().nullslast())
        )
        result = await self._db.execute(stmt)
        rows = result.scalars().all()
        return [_pos_to_dict(p) for p in rows]

    # ------------------------------------------------------------------
    # Position detail
    # ------------------------------------------------------------------

    async def get_position_detail(self, position_id: int) -> Optional[dict[str, Any]]:
        """Position + its slices (eagerly loaded)."""
        stmt = (
            select(Position)
            .options(selectinload(Position.slices))
            .where(Position.id == position_id)
        )
        result = await self._db.execute(stmt)
        pos = result.scalar_one_or_none()
        if pos is None:
            return None
        data = _pos_to_dict(pos)
        data["slices"] = [_slice_to_dict(s) for s in pos.slices]
        return data

    # ------------------------------------------------------------------
    # Timeline (lifecycle events)
    # ------------------------------------------------------------------

    async def get_position_timeline(
        self, position_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Chronological lifecycle events for a position."""
        stmt = (
            select(PositionLifecycleEvent)
            .where(PositionLifecycleEvent.position_id == position_id)
            .order_by(PositionLifecycleEvent.occurred_at.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        rows = result.scalars().all()
        return [_event_to_dict(e) for e in rows]

    # ------------------------------------------------------------------
    # Execution slices
    # ------------------------------------------------------------------

    async def get_position_slices(self, position_id: int) -> list[dict[str, Any]]:
        """All execution slices for a position."""
        stmt = (
            select(ExecutionSlice)
            .where(ExecutionSlice.position_id == position_id)
            .order_by(ExecutionSlice.created_at.desc())
        )
        result = await self._db.execute(stmt)
        rows = result.scalars().all()
        return [_slice_to_dict(s) for s in rows]

    async def get_stuck_slices(self, account_id: str) -> list[dict[str, Any]]:
        """Slices in STUCK status (may need manual intervention)."""
        stmt = (
            select(ExecutionSlice)
            .where(
                ExecutionSlice.account_id == account_id,
                ExecutionSlice.status == SliceStatus.STUCK.value,
            )
            .order_by(ExecutionSlice.stuck_at.desc().nullslast())
        )
        result = await self._db.execute(stmt)
        rows = result.scalars().all()
        return [_slice_to_dict(s) for s in rows]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def get_closing_reason_stats(
        self, account_id: str, days: int = 30
    ) -> dict[str, int]:
        """Distribution of closing reasons over the last N days."""
        since = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                Position.closing_reason,
                func.count(Position.id).label("cnt"),
            )
            .where(
                Position.account_id == account_id,
                Position.status.in_(
                    [PositionStatus.CLOSED.value, PositionStatus.LIQUIDATED.value]
                ),
                Position.closed_at >= since,
                Position.closing_reason.isnot(None),
            )
            .group_by(Position.closing_reason)
        )
        result = await self._db.execute(stmt)
        return {row.closing_reason: row.cnt for row in result}

    async def get_portfolio_summary(self, account_id: str) -> dict[str, Any]:
        """High-level counts for dashboard widgets."""
        active_stmt = select(func.count(Position.id)).where(
            Position.account_id == account_id,
            Position.status.in_(list(_ACTIVE_STATUSES)),
        )
        exception_stmt = select(func.count(Position.id)).where(
            Position.account_id == account_id,
            Position.status == PositionStatus.EXCEPTION.value,
        )
        stuck_stmt = select(func.count(ExecutionSlice.id)).where(
            ExecutionSlice.account_id == account_id,
            ExecutionSlice.status == SliceStatus.STUCK.value,
        )
        active_res = await self._db.execute(active_stmt)
        exception_res = await self._db.execute(exception_stmt)
        stuck_res = await self._db.execute(stuck_stmt)

        return {
            "active_positions": active_res.scalar_one() or 0,
            "exception_positions": exception_res.scalar_one() or 0,
            "stuck_slices": stuck_res.scalar_one() or 0,
        }


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _pos_to_dict(p: Position) -> dict[str, Any]:
    return {
        "id": p.id,
        "account_id": p.account_id,
        "symbol": p.symbol,
        "thesis_key": p.thesis_key,
        "status": p.status,
        "direction": p.direction,
        "total_qty": p.total_qty,
        "filled_qty": p.filled_qty,
        "open_qty": p.open_qty,
        "closed_qty": p.closed_qty,
        "avg_entry_price": p.avg_entry_price,
        "realized_pnl": p.realized_pnl,
        "unrealized_pnl_pct": p.unrealized_pnl_pct,
        "stop_loss_price": p.stop_loss_price,
        "take_profit_price": p.take_profit_price,
        "max_holding_days": p.max_holding_days,
        "execution_path": p.execution_path,
        "closing_reason": p.closing_reason,
        "closing_source": p.closing_source,
        "exemption_active": p.exemption_active,
        "exemption_detail": p.exemption_detail,
        "governance_flag": p.governance_flag,
        "initial_signal_id": p.initial_signal_id,
        "initial_signal_uid": p.initial_signal_uid,
        "latest_plan_id": p.latest_plan_id,
        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "last_action_at": p.last_action_at.isoformat() if p.last_action_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _slice_to_dict(s: ExecutionSlice) -> dict[str, Any]:
    return {
        "id": s.id,
        "position_id": s.position_id,
        "account_id": s.account_id,
        "symbol": s.symbol,
        "action": s.action,
        "status": s.status,
        "requested_qty": s.requested_qty,
        "submitted_qty": s.submitted_qty,
        "filled_qty": s.filled_qty,
        "avg_fill_price": s.avg_fill_price,
        "execution_path": s.execution_path,
        "closing_reason": s.closing_reason,
        "exemption_applied": s.exemption_applied,
        "signal_id": s.signal_id,
        "intent_id": s.intent_id,
        "order_ids": s.order_ids,
        "stuck_at": s.stuck_at.isoformat() if s.stuck_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _event_to_dict(e: PositionLifecycleEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "position_id": e.position_id,
        "slice_id": e.slice_id,
        "kind": e.kind,
        "summary": e.summary,
        "detail": e.detail,
        "from_status": e.from_status,
        "to_status": e.to_status,
        "actor": e.actor,
        "signal_id": e.signal_id,
        "intent_id": e.intent_id,
        "metadata": e.metadata_json,
        "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
    }
