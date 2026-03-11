from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.signal_engine import SignalEngine
from app.jobs.strategy_jobs import _sample_assets


class _FakeExecResult:
    def __init__(self, item):
        self._item = item

    def scalars(self):
        return self

    def first(self):
        return self._item


def test_sample_assets_emit_resonance_metadata_for_watchtower():
    assets = _sample_assets(
        count=3,
        strategy_name="量化策略",
        universe_symbols=["AAPL", "MSFT", "NVDA"],
    )

    assert len(assets) == 3
    signal_dimensions = assets[0]["signal_dimensions"]

    assert signal_dimensions["aligned_count"] >= 4
    assert "technical" in signal_dimensions["aligned_dims"]
    assert set(signal_dimensions["aligned_dims"]).isdisjoint(
        signal_dimensions["opposing_dims"]
    )
    assert len(signal_dimensions["dimensions"]) == 6
    assert {item["name"] for item in signal_dimensions["dimensions"]} == {
        "technical",
        "fundamental",
        "macro",
        "options",
        "flow",
        "sentiment",
    }
    assert signal_dimensions["adv_usd"] >= 2_000_000
    assert signal_dimensions["market_cap"] >= 800_000_000


@pytest.mark.asyncio
async def test_existing_signal_update_refreshes_watchtower_dimension_metadata():
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    existing_signal = SimpleNamespace(
        signal_strength=80.0,
        confidence=0.8,
        expected_return=0.02,
        risk_score=55.0,
        suggested_quantity=0.1,
        quantity_mode="PCT_EQUITY",
        quantity_value=0.1,
        priority=80,
        strategy_run_id="old-run",
        expired_at=None,
        factor_scores={"technical_score": 65.0},
        extra_metadata={"watchtower_stage": "SIGNAL_VALIDATION", "legacy_flag": True},
    )
    session.execute.return_value = _FakeExecResult(existing_signal)

    engine = object.__new__(SignalEngine)
    engine.session = session
    engine.risk_svc = cast(Any, None)
    engine.account_svc = cast(Any, None)
    engine.broker = cast(Any, None)

    sampled = _sample_assets(
        count=1,
        strategy_name="量化策略",
        universe_symbols=["AAPL"],
    )[0]
    signal_dims = sampled["signal_dimensions"]

    strategy_run = SimpleNamespace(
        account_id="acc-1",
        strategy_id="strat-1",
        id="run-1",
        direction="LONG",
        user_id="user-1",
        strategy_version="v1",
        target_universe="US_ALL_LOCAL",
        strategy=SimpleNamespace(name="Mock Strategy"),
    )
    asset = SimpleNamespace(
        symbol="AAPL",
        signal_strength=95.0,
        signal_dimensions=signal_dims,
    )

    result = await SignalEngine._create_signal_from_asset(
        engine,
        cast(Any, strategy_run),
        cast(Any, asset),
    )

    assert result is existing_signal
    assert existing_signal.signal_strength == 95.0
    assert existing_signal.extra_metadata["watchtower_stage"] == "SIGNAL_VALIDATION"
    assert existing_signal.extra_metadata["legacy_flag"] is True
    assert existing_signal.extra_metadata["strategy_name"] == "Mock Strategy"
    assert existing_signal.extra_metadata["aligned_count"] == signal_dims["aligned_count"]
    assert existing_signal.extra_metadata["aligned_dims"] == signal_dims["aligned_dims"]
    assert existing_signal.extra_metadata["dimensions"] == signal_dims["dimensions"]
    assert existing_signal.factor_scores["signal_dimensions"]["aligned_count"] == signal_dims["aligned_count"]
    assert existing_signal.factor_scores["dimensions"] == signal_dims["dimensions"]
    assert existing_signal.factor_scores["macro_score"] == signal_dims["macro_score"]
    assert existing_signal.factor_scores["options_score"] == signal_dims["options_score"]
    session.commit.assert_awaited()
    session.refresh.assert_awaited_with(existing_signal)
