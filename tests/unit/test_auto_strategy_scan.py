from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.engine.quant_trading_loop import QuantTradingLoop
from app.models.strategy import Strategy, StrategyRun
from app.services.strategy_auto_selection_service import StrategyAutoSelectionService
from app.services.strategy_service import StrategyService


@pytest.mark.asyncio
async def test_select_auto_scan_strategies_prefers_priority_then_fair_rotation():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Strategy.__table__.create)
        await conn.run_sync(StrategyRun.__table__.create)

    async with session_factory() as session:
        session.add_all(
            [
                Strategy(
                    id="builtin-never",
                    name="Builtin Never",
                    is_builtin=True,
                    is_active=True,
                    auto_scan_enabled=True,
                    auto_scan_priority=200,
                ),
                Strategy(
                    id="user-never",
                    name="User Never",
                    is_builtin=False,
                    is_active=True,
                    auto_scan_enabled=True,
                    auto_scan_priority=100,
                ),
                Strategy(
                    id="builtin-old",
                    name="Builtin Old",
                    is_builtin=True,
                    is_active=True,
                    auto_scan_enabled=True,
                    auto_scan_priority=200,
                    last_run_at=datetime(2026, 3, 1, 8, 0, 0),
                ),
                Strategy(
                    id="builtin-recent",
                    name="Builtin Recent",
                    is_builtin=True,
                    is_active=True,
                    auto_scan_enabled=True,
                    auto_scan_priority=200,
                    last_run_at=datetime(2026, 3, 10, 8, 0, 0),
                ),
                Strategy(
                    id="disabled-top",
                    name="Disabled Top",
                    is_builtin=True,
                    is_active=True,
                    auto_scan_enabled=False,
                    auto_scan_priority=1000,
                ),
                Strategy(
                    id="inactive-never",
                    name="Inactive Never",
                    is_builtin=True,
                    is_active=False,
                    auto_scan_enabled=True,
                    auto_scan_priority=500,
                ),
            ]
        )
        await session.commit()

        strategies = await StrategyAutoSelectionService.select_auto_scan_strategies(
            session,
            limit=3,
        )

    await engine.dispose()

    assert [strategy.id for strategy in strategies] == [
        "builtin-never",
        "builtin-old",
        "builtin-recent",
    ]


@pytest.mark.asyncio
async def test_update_auto_scan_config_persists_strategy_settings():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Strategy.__table__.create)
        await conn.run_sync(StrategyRun.__table__.create)

    async with session_factory() as session:
        session.add(
            Strategy(
                id="strategy-1",
                name="Strategy 1",
                is_builtin=True,
                is_active=True,
                auto_scan_enabled=True,
                auto_scan_priority=100,
            )
        )
        await session.commit()

        service = StrategyService(session)
        updated = await service.update_auto_scan_config(
            "strategy-1",
            False,
            320,
        )

    await engine.dispose()

    assert updated is not None
    assert updated.auto_scan_enabled is False
    assert updated.auto_scan_priority == 320


@pytest.mark.asyncio
async def test_trigger_runtime_strategy_scan_runs_multiple_candidates():
    loop = QuantTradingLoop(cast(Any, SimpleNamespace()))
    loop.strategy_run_svc.create_run = AsyncMock(
        side_effect=[
            SimpleNamespace(id="run-1"),
            SimpleNamespace(id="run-2"),
        ]
    )

    strategies = [
        SimpleNamespace(id="s-1", name="Strategy A"),
        SimpleNamespace(id="s-2", name="Strategy B"),
    ]
    execute_job = AsyncMock()

    with patch(
        (
            "app.engine.quant_trading_loop."
            "StrategyAutoSelectionService.select_auto_scan_strategies"
        ),
        new=AsyncMock(return_value=strategies),
    ), patch(
        "app.engine.quant_trading_loop.settings.AUTO_STRATEGY_SCAN_BATCH_SIZE",
        2,
    ), patch(
        "app.jobs.strategy_jobs.execute_strategy_run_job",
        new=execute_job,
    ):
        result = await loop._trigger_runtime_strategy_scan("acc-1")

    assert result["triggered"] is True
    assert result["triggered_count"] == 2
    assert [item["strategy_id"] for item in result["runs"]] == ["s-1", "s-2"]
    assert loop.strategy_run_svc.create_run.await_count == 2
    assert execute_job.await_count == 2
