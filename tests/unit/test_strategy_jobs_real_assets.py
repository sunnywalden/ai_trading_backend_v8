from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.engine.strategies.momentum_quality import MomentumQuality
from app.jobs.strategy_jobs import (
    _is_live_trading_context,
    _normalize_real_signal_payload,
    _resolve_strategy_implementation_key,
)


def test_resolve_strategy_implementation_key_supports_seeded_builtin_names():
    strategy = SimpleNamespace(
        id="550e8400-e29b-41d4-a716-446655440000",
        name="事件驱动趋势发现",
        style="事件驱动",
        tags=["event-driven", "momentum", "alpha"],
        signal_sources={"price": "breakout"},
        default_params={},
    )

    assert _resolve_strategy_implementation_key(strategy) == "breakout_momentum"


def test_normalize_real_signal_payload_marks_real_origin_and_dimensions():
    payload = _normalize_real_signal_payload(
        signal_data={
            "symbol": "AAPL",
            "direction": "BUY",
            "strength": 84,
            "weight": 0.25,
            "risk_score": 38,
            "metadata": {
                "strategy": "breakout_momentum",
                "historical_ic": 0.62,
                "timing_quality": 0.77,
            },
        },
        strategy_name="事件驱动趋势发现",
    )

    dims = payload["signal_dimensions"]
    assert payload["direction"] == "LONG"
    assert payload["action"] == "BUY"
    assert dims["signal_origin_mode"] == "REAL"
    assert dims["aligned_count"] >= 3
    assert isinstance(dims["dimensions"], list)
    assert dims["historical_ic"] == pytest.approx(0.62)
    assert dims["timing_quality"] == pytest.approx(0.77)


@pytest.mark.asyncio
async def test_momentum_quality_generates_real_candidates(monkeypatch):
    class _FakeMarketDataProvider:
        async def get_historical_prices(self, symbol, start_date, end_date):
            return [
                {"close": 100.0 + i, "open": 99.0 + i, "high": 101.0 + i, "low": 98.0 + i, "volume": 1_000_000 + i * 1000}
                for i in range(160)
            ]

        async def get_key_statistics(self, symbol):
            return {
                "roe": 0.24,
                "debt_to_equity": 35.0,
                "free_cash_flow": 10_000_000,
            }

    monkeypatch.setattr(
        "app.engine.strategies.momentum_quality.MarketDataProvider",
        _FakeMarketDataProvider,
    )

    strategy = MomentumQuality(
        params={
            "momentum_lookback": 120,
            "position_cap": 3,
            "momentum_weight": 0.6,
            "quality_weight": 0.4,
            "momentum_threshold": 0.05,
        },
        session=cast(Any, SimpleNamespace()),
    )

    signals = await strategy.generate_signals(universe=["AAPL", "MSFT", "NVDA"])

    assert len(signals) == 3
    assert all(signal["direction"] == "BUY" for signal in signals)
    assert all(signal["strength"] >= 65 for signal in signals)
    assert all(signal["metadata"]["strategy"] == "momentum_quality" for signal in signals)


def test_live_trading_context_detects_real_modes(monkeypatch):
    monkeypatch.setattr("app.jobs.strategy_jobs.settings.TRADE_MODE", "REAL")
    monkeypatch.setattr("app.jobs.strategy_jobs.settings.ORDER_MODE", "REAL")

    assert _is_live_trading_context() is True
