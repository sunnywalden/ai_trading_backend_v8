from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.meta_state_snapshot import MetaStateSnapshot as MetaStateSnapshotRecord
from app.services.meta_state_snapshot_service import MetaStateSnapshotService


@pytest.mark.asyncio
async def test_build_snapshot_persists_to_db_and_can_be_loaded_back():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(MetaStateSnapshotRecord.__table__.create)

    service = MetaStateSnapshotService(redis_client=None)

    async with session_factory() as session:
        with patch.object(
            service,
            "_gather_throttled_signals",
            AsyncMock(
                return_value=[
                    {
                        "symbol": "AAPL",
                        "direction": "LONG",
                        "rejection_count": 3,
                    }
                ]
            ),
        ), patch.object(
            service,
            "_gather_false_hold_alerts",
            AsyncMock(return_value=[{"symbol": "MSFT", "cycle_count": 3}]),
        ):
            snap = await service.build_snapshot(
                account_id="ACC001",
                positions={"AAPL": {"qty": 10, "current_price": 100.0}},
                equity=10_000.0,
                db=session,
            )

        loaded = await service.get_latest_snapshot(db=session, account_id="ACC001")

    await engine.dispose()

    assert snap.account_id == "ACC001"
    assert loaded is not None
    assert loaded.account_id == "ACC001"
    assert loaded.model_state["total_blocked_signals"] == 2
    assert loaded.capital_state["positions_count"] == 1
