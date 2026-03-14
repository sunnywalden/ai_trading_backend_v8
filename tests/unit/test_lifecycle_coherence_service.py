from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.db import Base
from app.models.position import Position, PositionStatus
from app.models.position_lifecycle_event import PositionLifecycleEvent
from app.models.trading_plan import TradingPlan
from app.services.lifecycle_coherence_service import lifecycle_coherence_service


@pytest.mark.asyncio
async def test_lifecycle_coherence_auto_closes_stale_plan_and_position(
    monkeypatch,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    stale_time = datetime.now(timezone.utc) - timedelta(hours=2)

    async with session_factory() as session:
        plan = TradingPlan(
            account_id="acc-1",
            symbol="MSFT",
            plan_type="AUTONOMOUS",
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit=Decimal("110"),
            target_position=Decimal("0.10"),
            plan_status="EXECUTED",
            direction="BUY",
            source="AI_AUTONOMOUS",
            pipeline_stage=9,
            stage_entered_at=stale_time,
            position_fsm_state="HELD",
            created_at=stale_time.replace(tzinfo=None),
            updated_at=stale_time.replace(tzinfo=None),
        )
        session.add(plan)
        await session.flush()

        position = Position(
            account_id="acc-1",
            symbol="MSFT",
            thesis_key="default",
            status=PositionStatus.ACTIVE.value,
            direction="LONG",
            total_qty=100.0,
            filled_qty=100.0,
            open_qty=100.0,
            closed_qty=0.0,
            latest_plan_id=plan.id,
            opened_at=stale_time.replace(tzinfo=None),
            last_action_at=stale_time.replace(tzinfo=None),
            updated_at=stale_time.replace(tzinfo=None),
        )
        session.add(position)
        await session.commit()

        monkeypatch.setattr(
            (
                "app.services.lifecycle_coherence_service."
                "truth_source_service.get_positions_read_model"
            ),
            AsyncMock(
                side_effect=[
                    {
                        "items": [
                            {
                                "symbol": "AAPL",
                                "broker_live": True,
                            }
                        ],
                        "source": "BROKER_LIVE_OVERRIDE",
                        "active_positions": 1,
                        "broker_active_positions": 1,
                        "lifecycle_active_positions": 1,
                        "mismatch_detected": True,
                        "mismatch_symbols": ["AAPL", "MSFT"],
                    },
                    {
                        "items": [
                            {
                                "symbol": "AAPL",
                                "broker_live": True,
                            }
                        ],
                        "source": "BROKER_LIVE",
                        "active_positions": 1,
                        "broker_active_positions": 1,
                        "lifecycle_active_positions": 1,
                        "mismatch_detected": False,
                        "mismatch_symbols": [],
                    },
                ]
            ),
        )

        summary = await lifecycle_coherence_service.inspect_and_reconcile(
            session,
            account_id="acc-1",
            auto_heal=True,
        )

        refreshed_plan = (
            await session.execute(select(TradingPlan).where(TradingPlan.id == plan.id))
        ).scalar_one()
        refreshed_position = (
            await session.execute(select(Position).where(Position.id == position.id))
        ).scalar_one()
        lifecycle_events = (
            (await session.execute(select(PositionLifecycleEvent))).scalars().all()
        )

    assert summary["mismatch_detected"] is False
    assert summary["source"] == "BROKER_LIVE"
    assert summary["stale_plans_closed"] == 1
    assert summary["stale_positions_closed"] == 1
    assert summary["hydrated_positions_created"] == 1
    assert summary["reconciled_plan_ids"] == [plan.id]
    assert summary["reconciled_position_ids"] == [position.id]
    assert len(summary["hydrated_position_ids"]) == 1

    assert refreshed_plan.pipeline_stage == 12
    assert refreshed_plan.position_fsm_state == "CLOSED"
    assert refreshed_position.status == PositionStatus.CLOSED.value
    assert refreshed_position.open_qty == pytest.approx(0.0)
    assert refreshed_position.total_qty == pytest.approx(0.0)
    assert refreshed_position.closing_source == "BROKER_SYNC"
    assert len(lifecycle_events) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_lifecycle_coherence_inspect_only_when_no_mismatch(monkeypatch):
    monkeypatch.setattr(
        (
            "app.services.lifecycle_coherence_service."
            "truth_source_service.get_positions_read_model"
        ),
        AsyncMock(
            return_value={
                "items": [{"symbol": "AAPL", "broker_live": True}],
                "source": "BROKER_LIVE",
                "active_positions": 1,
                "broker_active_positions": 1,
                "lifecycle_active_positions": 1,
                "mismatch_detected": False,
                "mismatch_symbols": [],
            }
        ),
    )

    summary = await lifecycle_coherence_service.inspect_and_reconcile(
        AsyncMock(),
        account_id="acc-1",
        auto_heal=True,
    )

    assert summary["run_mode"] == "inspect_only"
    assert summary["mismatch_detected"] is False
    assert summary["stale_plans_closed"] == 0
    assert summary["stale_positions_closed"] == 0
    assert summary["hydrated_positions_created"] == 0


@pytest.mark.asyncio
async def test_lifecycle_coherence_reuses_closed_broker_live_shadow_position(
    monkeypatch,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    closed_time = datetime.now(timezone.utc) - timedelta(days=1)

    async with session_factory() as session:
        existing = Position(
            account_id="acc-1",
            symbol="AAPL",
            thesis_key="broker-live",
            status=PositionStatus.CLOSED.value,
            direction="LONG",
            total_qty=0.0,
            filled_qty=0.0,
            open_qty=0.0,
            closed_qty=10.0,
            closed_at=closed_time.replace(tzinfo=None),
            last_action_at=closed_time.replace(tzinfo=None),
            closing_source="BROKER_SYNC",
        )
        session.add(existing)
        await session.commit()

        monkeypatch.setattr(
            (
                "app.services.lifecycle_coherence_service."
                "truth_source_service.get_positions_read_model"
            ),
            AsyncMock(
                side_effect=[
                    {
                        "items": [
                            {
                                "symbol": "AAPL",
                                "broker_live": True,
                                "total_qty": 25.0,
                                "direction": "LONG",
                            }
                        ],
                        "source": "BROKER_LIVE_OVERRIDE",
                        "active_positions": 1,
                        "broker_active_positions": 1,
                        "lifecycle_active_positions": 0,
                        "mismatch_detected": True,
                        "mismatch_symbols": ["AAPL"],
                    },
                    {
                        "items": [
                            {
                                "symbol": "AAPL",
                                "broker_live": True,
                            }
                        ],
                        "source": "BROKER_LIVE",
                        "active_positions": 1,
                        "broker_active_positions": 1,
                        "lifecycle_active_positions": 1,
                        "mismatch_detected": False,
                        "mismatch_symbols": [],
                    },
                ]
            ),
        )

        summary = await lifecycle_coherence_service.inspect_and_reconcile(
            session,
            account_id="acc-1",
            auto_heal=True,
        )

        positions = (
            (
                await session.execute(
                    select(Position)
                    .where(
                        Position.account_id == "acc-1",
                        Position.symbol == "AAPL",
                    )
                    .order_by(Position.id)
                )
            )
            .scalars()
            .all()
        )

    assert summary["mismatch_detected"] is False
    assert summary["hydrated_positions_created"] == 1
    assert len(positions) == 1
    assert positions[0].status == PositionStatus.ACTIVE.value
    assert positions[0].id == existing.id
    assert positions[0].open_qty == pytest.approx(25.0)
    assert positions[0].closed_at is None

    await engine.dispose()
