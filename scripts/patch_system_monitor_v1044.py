"""Patch system_monitor.py: add V10.4.4 Position helper functions."""

import os
import sys

TARGET = os.path.join(
    os.path.dirname(__file__),
    "..",
    "app",
    "routers",
    "system_monitor.py",
)

NEW_HELPERS = '''
# ---------------------------------------------------------------------------
# V10.4.4 Position-centric helper queries (safe: return 0 if tables missing)
# ---------------------------------------------------------------------------

async def _count_positions(db: AsyncSession, mode: str) -> int:
    """Count positions by mode: 'active' or 'exception'."""
    try:
        from app.models.position import Position, PositionStatus
        from sqlalchemy import func as sa_func

        _ACTIVE = {
            PositionStatus.PENDING.value,
            PositionStatus.OPENING.value,
            PositionStatus.ACTIVE.value,
            PositionStatus.SCALING_IN.value,
            PositionStatus.SCALING_OUT.value,
            PositionStatus.CLOSING.value,
            PositionStatus.PARTIALLY_CLOSED.value,
            PositionStatus.EXCEPTION.value,
        }
        if mode == "exception":
            stmt = select(sa_func.count(Position.id)).where(
                Position.status == PositionStatus.EXCEPTION.value
            )
        else:
            stmt = select(sa_func.count(Position.id)).where(
                Position.status.in_(list(_ACTIVE))
            )
        result = await db.execute(stmt)
        return result.scalar_one() or 0
    except Exception:
        return 0


async def _count_stuck_slices(db: AsyncSession) -> int:
    """Count execution slices in STUCK status."""
    try:
        from app.models.execution_slice import ExecutionSlice, SliceStatus
        from sqlalchemy import func as sa_func

        stmt = select(sa_func.count(ExecutionSlice.id)).where(
            ExecutionSlice.status == SliceStatus.STUCK.value
        )
        result = await db.execute(stmt)
        return result.scalar_one() or 0
    except Exception:
        return 0


async def _get_closing_reason_dist(db: AsyncSession, days: int) -> dict:
    """Return closing-reason distribution from Position table."""
    from datetime import timedelta

    try:
        from app.models.position import Position, PositionStatus
        from sqlalchemy import func as sa_func

        since = _now().replace(tzinfo=None) - timedelta(days=days)
        stmt = (
            select(
                Position.closing_reason,
                sa_func.count(Position.id).label("cnt"),
            )
            .where(
                Position.status.in_(
                    [
                        PositionStatus.CLOSED.value,
                        PositionStatus.LIQUIDATED.value,
                    ]
                ),
                Position.closed_at >= since,
                Position.closing_reason.isnot(None),
            )
            .group_by(Position.closing_reason)
        )
        result = await db.execute(stmt)
        return {row.closing_reason: row.cnt for row in result}
    except Exception:
        return {}


'''

with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

ANCHOR = "async def _load_recent_plans("
if ANCHOR not in content:
    print("ERROR: anchor not found")
    sys.exit(1)

new_content = content.replace(ANCHOR, NEW_HELPERS + ANCHOR, 1)

with open(TARGET, "w", encoding="utf-8") as f:
    f.write(new_content)

print("DONE: V10.4.4 position helper functions inserted.")
