from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.config import settings
from app.models.fsm_transition_log import FsmTransitionLog
from app.models.position import ClosingReason, Position, PositionStatus
from app.models.position_lifecycle_event import EventKind, PositionLifecycleEvent
from app.models.trading_plan import TradingPlan
from app.services.position_query_service import ACTIVE_POSITION_STATUSES
from app.services.truth_source_service import truth_source_service

logger = logging.getLogger(__name__)

_STALE_PLAN_STAGES = frozenset({9, 10, 11})
_STALE_PLAN_GRACE = timedelta(minutes=15)
_STALE_POSITION_GRACE = timedelta(minutes=15)


class LifecycleCoherenceService:
    """统一双视角协同：检测 broker/live 与本地生命周期的失配并自动收口。"""

    async def resolve_account_id(self) -> Optional[str]:
        try:
            broker = make_option_broker_client()
            resolved = await broker.get_account_id()
            if resolved:
                return str(resolved)
        except (AttributeError, OSError, RuntimeError, ValueError):
            logger.debug("[LifecycleCoherence] failed to resolve account from broker")

        fallback = str(getattr(settings, "TIGER_ACCOUNT", "") or "").strip()
        return fallback or None

    @staticmethod
    def _normalize_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _is_stale(
        reference: Optional[datetime],
        *,
        now: datetime,
        threshold: timedelta,
    ) -> bool:
        normalized = LifecycleCoherenceService._normalize_utc(reference)
        if normalized is None:
            return True
        return now - normalized >= threshold

    @staticmethod
    def _build_summary(
        *,
        account_id: Optional[str],
        read_model: dict,
        stale_plans_closed: int = 0,
        stale_positions_closed: int = 0,
        hydrated_positions_created: int = 0,
        reconciled_plan_ids: Optional[list[int]] = None,
        reconciled_position_ids: Optional[list[int]] = None,
        hydrated_position_ids: Optional[list[int]] = None,
        run_mode: str = "inspect_only",
        notes: Optional[list[str]] = None,
    ) -> dict:
        return {
            "account_id": account_id,
            "source": str(read_model.get("source") or "UNKNOWN"),
            "active_positions": int(read_model.get("active_positions") or 0),
            "broker_active_positions": int(
                read_model.get("broker_active_positions") or 0
            ),
            "lifecycle_active_positions": int(
                read_model.get("lifecycle_active_positions") or 0
            ),
            "mismatch_detected": bool(read_model.get("mismatch_detected")),
            "mismatch_symbols": list(read_model.get("mismatch_symbols") or []),
            "stale_plans_closed": stale_plans_closed,
            "stale_positions_closed": stale_positions_closed,
            "hydrated_positions_created": hydrated_positions_created,
            "reconciled_plan_ids": reconciled_plan_ids or [],
            "reconciled_position_ids": reconciled_position_ids or [],
            "hydrated_position_ids": hydrated_position_ids or [],
            "run_mode": run_mode,
            "notes": notes or [],
            "as_of": datetime.now(timezone.utc),
        }

    def _inspect_read_model(
        self,
        *,
        account_id: str,
        read_model: dict,
        auto_heal: bool,
    ) -> tuple[Optional[dict], set[str], list[str]]:
        broker_live_items = [
            item
            for item in (read_model.get("items") or [])
            if bool(item.get("broker_live"))
        ]
        live_symbols = {
            str(item.get("symbol") or "")
            for item in broker_live_items
            if item.get("symbol")
        }
        notes: list[str] = []

        if not broker_live_items:
            notes.append("broker-live snapshot unavailable, skipped auto-heal")
            return (
                self._build_summary(
                    account_id=account_id,
                    read_model=read_model,
                    run_mode="inspect_only",
                    notes=notes,
                ),
                live_symbols,
                notes,
            )

        if not bool(read_model.get("mismatch_detected")):
            notes.append("broker/live and lifecycle views are already aligned")
            return (
                self._build_summary(
                    account_id=account_id,
                    read_model=read_model,
                    run_mode="inspect_only",
                    notes=notes,
                ),
                live_symbols,
                notes,
            )

        if not auto_heal:
            notes.append("mismatch detected but auto-heal disabled")
            return (
                self._build_summary(
                    account_id=account_id,
                    read_model=read_model,
                    run_mode="inspect_only",
                    notes=notes,
                ),
                live_symbols,
                notes,
            )

        return None, live_symbols, notes

    @staticmethod
    def _plan_reference_time(plan: TradingPlan) -> Optional[datetime]:
        return (
            LifecycleCoherenceService._normalize_utc(plan.stage_entered_at)
            or LifecycleCoherenceService._normalize_utc(plan.updated_at)
            or LifecycleCoherenceService._normalize_utc(plan.created_at)
        )

    @staticmethod
    def _position_reference_time(position: Position) -> Optional[datetime]:
        return (
            LifecycleCoherenceService._normalize_utc(position.last_action_at)
            or LifecycleCoherenceService._normalize_utc(position.updated_at)
            or LifecycleCoherenceService._normalize_utc(position.opened_at)
            or LifecycleCoherenceService._normalize_utc(position.created_at)
        )

    def _reconcile_plan(
        self,
        *,
        db: AsyncSession,
        plan: TradingPlan,
        now: datetime,
    ) -> int:
        old_stage = plan.pipeline_stage
        old_position_fsm = plan.position_fsm_state
        plan.pipeline_stage = 12
        plan.stage_entered_at = now
        plan.position_fsm_state = "CLOSED"

        db.add(
            FsmTransitionLog(
                plan_id=plan.id,
                fsm_type="PLAN",
                from_state=(
                    f"STAGE_{old_stage}" if old_stage is not None else "UNKNOWN"
                ),
                to_state="STAGE_12",
                engine="lifecycle_coherence",
                trigger_reason=(
                    "lifecycle_coherence: broker live missing position → "
                    "force close stale plan to S12"
                ),
            )
        )
        if old_position_fsm != "CLOSED":
            db.add(
                FsmTransitionLog(
                    plan_id=plan.id,
                    fsm_type="POSITION",
                    from_state=old_position_fsm,
                    to_state="CLOSED",
                    engine="lifecycle_coherence",
                    trigger_reason=(
                        "lifecycle_coherence: broker live missing position → "
                        "close stale position FSM"
                    ),
                )
            )
        return plan.id

    def _reconcile_position(
        self,
        *,
        db: AsyncSession,
        position: Position,
        now: datetime,
        live_symbols: set[str],
    ) -> int:
        old_status = str(position.status or PositionStatus.ACTIVE.value)
        qty_before = float(position.open_qty or position.total_qty or 0.0)
        position.status = PositionStatus.CLOSED.value
        position.closed_at = now
        position.last_action_at = now
        position.closing_reason = ClosingReason.MANUAL_OVERRIDE.value
        position.closing_source = "BROKER_SYNC"
        existing_note = str(position.closing_note or "").strip()
        auto_note = (
            "lifecycle_coherence auto-close: broker live has no active "
            "position for this symbol"
        )
        position.closing_note = (
            f"{existing_note} | {auto_note}" if existing_note else auto_note
        )
        position.closed_qty = max(float(position.closed_qty or 0.0), qty_before)
        position.open_qty = 0.0
        position.total_qty = 0.0
        position.unrealized_pnl = 0.0
        position.unrealized_pnl_pct = 0.0

        db.add(
            PositionLifecycleEvent(
                position_id=position.id,
                kind=EventKind.BROKER_SYNC.value,
                summary="Broker live mismatch auto-closed stale position",
                detail=(
                    "lifecycle_coherence detected that broker/live no longer "
                    "holds this symbol and closed the stale local position "
                    "record."
                ),
                from_status=old_status,
                to_status=PositionStatus.CLOSED.value,
                actor="lifecycle_coherence",
                metadata_json={
                    "broker_live_symbols": sorted(live_symbols),
                    "qty_before_close": qty_before,
                    "reason": "broker_live_missing_position",
                },
                occurred_at=now,
            )
        )

        if position.latest_plan_id:
            db.add(
                FsmTransitionLog(
                    plan_id=int(position.latest_plan_id),
                    fsm_type="POSITION",
                    from_state=old_status,
                    to_state=PositionStatus.CLOSED.value,
                    engine="lifecycle_coherence",
                    trigger_reason=(
                        "lifecycle_coherence: broker live missing position → "
                        "close stale Position aggregate"
                    ),
                )
            )
        return position.id

    async def _get_existing_broker_live_position(
        self,
        *,
        db: AsyncSession,
        account_id: str,
        symbol: str,
    ) -> Optional[Position]:
        return (
            await db.execute(
                select(Position)
                .where(
                    Position.account_id == account_id,
                    Position.symbol == symbol,
                    Position.thesis_key == "broker-live",
                )
                .order_by(desc(Position.updated_at), desc(Position.id))
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _upsert_hydrated_position(
        self,
        *,
        db: AsyncSession,
        account_id: str,
        symbol: str,
        qty: float,
        item: dict,
        now: datetime,
    ) -> Position:
        position = await self._get_existing_broker_live_position(
            db=db,
            account_id=account_id,
            symbol=symbol,
        )
        if position is None:
            position = Position(
                account_id=account_id,
                symbol=symbol,
                thesis_key="broker-live",
            )
            db.add(position)
            await db.flush()

        position.status = PositionStatus.ACTIVE.value
        position.direction = str(item.get("direction") or "LONG")
        position.total_qty = qty
        position.filled_qty = qty
        position.open_qty = qty
        position.closed_qty = 0.0
        position.avg_entry_price = float(item.get("avg_entry_price") or 0.0) or None
        position.unrealized_pnl_pct = float(item.get("unrealized_pnl_pct") or 0.0)
        position.unrealized_pnl = float(item.get("unrealized_pnl") or 0.0)
        position.opened_at = position.opened_at or now
        position.closed_at = None
        position.last_action_at = now
        position.closing_reason = None
        position.closing_source = None
        position.closing_note = None
        return position

    async def _hydrate_missing_positions(
        self,
        *,
        db: AsyncSession,
        account_id: str,
        broker_live_items: list[dict],
        now: datetime,
    ) -> list[int]:
        active_rows = (
            (
                await db.execute(
                    select(Position)
                    .where(
                        Position.account_id == account_id,
                        Position.status.in_(tuple(ACTIVE_POSITION_STATUSES)),
                    )
                    .order_by(desc(Position.updated_at), desc(Position.id))
                )
            )
            .scalars()
            .all()
        )
        active_symbols = {str(row.symbol or "") for row in active_rows if row.symbol}

        hydrated_ids: list[int] = []
        for item in broker_live_items:
            symbol = str(item.get("symbol") or "").strip()
            if not symbol or symbol in active_symbols:
                continue

            qty = float(
                item.get("open_qty")
                or item.get("total_qty")
                or item.get("filled_qty")
                or 0.0
            )
            position = await self._upsert_hydrated_position(
                db=db,
                account_id=account_id,
                symbol=symbol,
                qty=qty,
                item=item,
                now=now,
            )

            db.add(
                PositionLifecycleEvent(
                    position_id=position.id,
                    kind=EventKind.BROKER_SYNC.value,
                    summary=("Hydrated broker/live position into lifecycle aggregate"),
                    detail=(
                        "lifecycle_coherence created a broker-live shadow "
                        "Position record because this symbol existed at the "
                        "broker but not in the local lifecycle aggregate."
                    ),
                    from_status=None,
                    to_status=PositionStatus.ACTIVE.value,
                    actor="lifecycle_coherence",
                    metadata_json={
                        "symbol": symbol,
                        "qty": qty,
                        "truth_source": (item.get("truth_source") or "BROKER_LIVE"),
                        "reason": "broker_live_missing_local_position",
                    },
                    occurred_at=now,
                )
            )

            hydrated_ids.append(position.id)
            active_symbols.add(symbol)

        return hydrated_ids

    async def _reconcile_stale_plans(
        self,
        *,
        db: AsyncSession,
        account_id: str,
        live_symbols: set[str],
        now: datetime,
    ) -> list[int]:
        plan_rows = (
            (
                await db.execute(
                    select(TradingPlan)
                    .where(
                        TradingPlan.account_id == account_id,
                        TradingPlan.plan_status == "EXECUTED",
                        TradingPlan.pipeline_stage.in_(tuple(_STALE_PLAN_STAGES)),
                    )
                    .order_by(desc(TradingPlan.updated_at), desc(TradingPlan.id))
                )
            )
            .scalars()
            .all()
        )

        reconciled: list[int] = []
        for plan in plan_rows:
            if plan.symbol in live_symbols:
                continue
            if not self._is_stale(
                self._plan_reference_time(plan),
                now=now,
                threshold=_STALE_PLAN_GRACE,
            ):
                continue
            reconciled.append(self._reconcile_plan(db=db, plan=plan, now=now))
        return reconciled

    async def _reconcile_stale_positions(
        self,
        *,
        db: AsyncSession,
        account_id: str,
        live_symbols: set[str],
        now: datetime,
    ) -> list[int]:
        position_rows = (
            (
                await db.execute(
                    select(Position)
                    .where(
                        Position.account_id == account_id,
                        Position.status.in_(tuple(ACTIVE_POSITION_STATUSES)),
                    )
                    .order_by(desc(Position.updated_at), desc(Position.id))
                )
            )
            .scalars()
            .all()
        )

        reconciled: list[int] = []
        for position in position_rows:
            if position.symbol in live_symbols:
                continue
            if not self._is_stale(
                self._position_reference_time(position),
                now=now,
                threshold=_STALE_POSITION_GRACE,
            ):
                continue
            reconciled.append(
                self._reconcile_position(
                    db=db,
                    position=position,
                    now=now,
                    live_symbols=live_symbols,
                )
            )
        return reconciled

    async def inspect_and_reconcile(
        self,
        db: AsyncSession,
        account_id: str,
        *,
        auto_heal: bool = True,
    ) -> dict:
        read_model = await truth_source_service.get_positions_read_model(
            db,
            account_id,
        )
        broker_live_items = [
            item
            for item in (read_model.get("items") or [])
            if bool(item.get("broker_live"))
        ]
        summary, live_symbols, notes = self._inspect_read_model(
            account_id=account_id,
            read_model=read_model,
            auto_heal=auto_heal,
        )
        if summary is not None:
            return summary

        now = datetime.now(timezone.utc)
        reconciled_plan_ids = await self._reconcile_stale_plans(
            db=db,
            account_id=account_id,
            live_symbols=live_symbols,
            now=now,
        )
        reconciled_position_ids = await self._reconcile_stale_positions(
            db=db,
            account_id=account_id,
            live_symbols=live_symbols,
            now=now,
        )
        hydrated_position_ids = await self._hydrate_missing_positions(
            db=db,
            account_id=account_id,
            broker_live_items=broker_live_items,
            now=now,
        )

        has_changes = bool(
            reconciled_plan_ids or reconciled_position_ids or hydrated_position_ids
        )
        if has_changes:
            await db.commit()
            logger.info(
                "[LifecycleCoherence] account=%s stale_plans_closed=%s "
                "stale_positions_closed=%s hydrated_positions=%s symbols=%s",
                account_id,
                len(reconciled_plan_ids),
                len(reconciled_position_ids),
                len(hydrated_position_ids),
                sorted(live_symbols),
            )
        else:
            await db.rollback()
            notes.append(
                "mismatch detected but no stale records exceeded auto-heal " "threshold"
            )

        final_read_model = read_model
        if has_changes:
            final_read_model = await truth_source_service.get_positions_read_model(
                db,
                account_id,
            )

        return self._build_summary(
            account_id=account_id,
            read_model=final_read_model,
            stale_plans_closed=len(reconciled_plan_ids),
            stale_positions_closed=len(reconciled_position_ids),
            hydrated_positions_created=len(hydrated_position_ids),
            reconciled_plan_ids=reconciled_plan_ids,
            reconciled_position_ids=reconciled_position_ids,
            hydrated_position_ids=hydrated_position_ids,
            run_mode="auto_heal",
            notes=notes,
        )


lifecycle_coherence_service = LifecycleCoherenceService()
