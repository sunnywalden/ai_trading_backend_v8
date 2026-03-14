from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.improvement_candidate import ImprovementCandidate
from app.services.improvement_candidate_service import improvement_candidate_service


@pytest.mark.asyncio
async def test_generate_from_meta_state_creates_expected_candidates():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(ImprovementCandidate.__table__.create)

    snapshot = {
        "capital_state": {"idle_cash_ratio": 0.36},
        "model_state": {
            "active_friction_tickers": 2,
            "soft_relief_eligible_count": 1,
            "false_hold_count": 1,
        },
    }

    async with session_factory() as session:
        with patch(
            "app.services.improvement_candidate_service.settings.IMPROVEMENT_ENGINE_V1101_ENABLED",
            True,
        ):
            rows = await improvement_candidate_service.generate_from_meta_state(
                session,
                account_id="ACC001",
                snapshot=snapshot,
            )

        persisted = (
            (await session.execute(select(ImprovementCandidate))).scalars().all()
        )

    await engine.dispose()

    assert len(rows) == 3
    assert len(persisted) == 3
    params = {row.target_param for row in persisted}
    assert "idle_capital_headroom_factor" in params
    assert "soft_threshold_delta" in params
    assert "false_hold_detection_rounds" in params


@pytest.mark.asyncio
async def test_generate_from_meta_state_deduplicates_pending_candidates():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(ImprovementCandidate.__table__.create)

    snapshot = {
        "capital_state": {"idle_cash_ratio": 0.36},
        "model_state": {
            "active_friction_tickers": 1,
            "soft_relief_eligible_count": 1,
            "false_hold_count": 0,
        },
    }

    async with session_factory() as session:
        with patch(
            "app.services.improvement_candidate_service.settings.IMPROVEMENT_ENGINE_V1101_ENABLED",
            True,
        ):
            await improvement_candidate_service.generate_from_meta_state(
                session,
                account_id="ACC001",
                snapshot=snapshot,
            )
            second = await improvement_candidate_service.generate_from_meta_state(
                session,
                account_id="ACC001",
                snapshot=snapshot,
            )

        persisted = (
            (await session.execute(select(ImprovementCandidate))).scalars().all()
        )

    await engine.dispose()

    assert second == []
    assert len(persisted) == 2
