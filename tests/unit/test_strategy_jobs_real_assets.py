from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.engine.strategies.momentum_quality import MomentumQuality
from app.jobs.strategy_jobs import (
    _is_live_trading_context,
    _normalize_real_signal_payload,
    _probe_hk_historical_ready_symbols,
    _resolve_market_by_runtime,
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
        async def get_historical_prices(self, symbol, start_date, end_date, **kwargs):
            return [
                {"close": 100.0 + i, "open": 99.0 + i, "high": 101.0 + i, "low": 98.0 + i, "volume": 1_000_000 + i * 1000}
                for i in range(160)
            ]

        async def get_key_statistics(self, symbol, **kwargs):
            return {
                "roe": 0.24,
                "debt_to_equity": 35.0,
                "free_cash_flow": 10_000_000,
            }

    monkeypatch.setattr(
        "app.engine.strategies.momentum_quality.market_data_provider",
        _FakeMarketDataProvider(),
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


@pytest.mark.asyncio
async def test_momentum_quality_tolerates_missing_key_statistics(monkeypatch):
    class _FakeMarketDataProvider:
        async def get_historical_prices(self, symbol, start_date, end_date, **kwargs):
            return [
                {"close": 100.0 + i, "open": 99.0 + i, "high": 101.0 + i, "low": 98.0 + i, "volume": 1_000_000 + i * 1000}
                for i in range(160)
            ]

        async def get_key_statistics(self, symbol, **kwargs):
            raise RuntimeError("stats unavailable")

    monkeypatch.setattr(
        "app.engine.strategies.momentum_quality.market_data_provider",
        _FakeMarketDataProvider(),
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

    signals = await strategy.generate_signals(universe=["00700", "09988", "03690"])

    assert len(signals) == 3
    assert all(signal["metadata"]["quality_score"] is None for signal in signals)
    assert all(signal["direction"] == "BUY" for signal in signals)


@pytest.mark.asyncio
async def test_momentum_quality_ranked_fallback_uses_real_data_when_threshold_not_met(monkeypatch):
    class _FakeMarketDataProvider:
        async def get_historical_prices(self, symbol, start_date, end_date, **kwargs):
            base = {
                "00700": 100.0,
                "09988": 98.0,
                "03690": 97.5,
            }[symbol]
            closes = [base + i * 0.02 for i in range(160)]
            return [
                {"close": close, "open": close - 0.1, "high": close + 0.2, "low": close - 0.2, "volume": 1_000_000}
                for close in closes
            ]

        async def get_key_statistics(self, symbol, **kwargs):
            return {}

    monkeypatch.setattr(
        "app.engine.strategies.momentum_quality.market_data_provider",
        _FakeMarketDataProvider(),
    )

    strategy = MomentumQuality(
        params={
            "momentum_lookback": 120,
            "position_cap": 2,
            "momentum_threshold": 0.05,
            "fallback_momentum_floor": -0.05,
        },
        session=cast(Any, SimpleNamespace()),
    )

    signals = await strategy.generate_signals(universe=["00700", "09988", "03690"])

    assert len(signals) == 2
    assert all(signal["metadata"]["used_ranked_fallback"] is True for signal in signals)
    assert all(signal["direction"] == "BUY" for signal in signals)


@pytest.mark.asyncio
async def test_momentum_quality_generates_sell_signals_for_negative_momentum(monkeypatch):
    class _FakeMarketDataProvider:
        async def get_historical_prices(self, symbol, start_date, end_date, **kwargs):
            closes = [150.0 - i * 0.5 for i in range(160)]
            return [
                {"close": close, "open": close + 0.2, "high": close + 0.4, "low": close - 0.4, "volume": 1_000_000}
                for close in closes
            ]

        async def get_key_statistics(self, symbol, **kwargs):
            return {"roe": 0.2, "debt_to_equity": 20.0, "free_cash_flow": 1_000_000}

    monkeypatch.setattr(
        "app.engine.strategies.momentum_quality.market_data_provider",
        _FakeMarketDataProvider(),
    )

    strategy = MomentumQuality(
        params={
            "momentum_lookback": 120,
            "position_cap": 2,
            "momentum_threshold": 0.05,
            "short_momentum_threshold": 0.05,
        },
        session=cast(Any, SimpleNamespace()),
    )

    signals = await strategy.generate_signals(universe=["00700", "09988"])

    assert len(signals) == 2
    assert all(signal["direction"] == "SELL" for signal in signals)
    assert all(signal["metadata"]["position_bias"] == "SHORT" for signal in signals)


def test_live_trading_context_detects_real_modes(monkeypatch):
    monkeypatch.setattr("app.jobs.strategy_jobs.settings.TRADE_MODE", "REAL")
    monkeypatch.setattr("app.jobs.strategy_jobs.settings.ORDER_MODE", "REAL")

    assert _is_live_trading_context() is True


@pytest.mark.asyncio
async def test_probe_hk_historical_ready_symbols_prefers_real_ready_subset(monkeypatch):
    class _FakeMarketDataProvider:
        async def get_historical_prices(self, symbol, start_date, end_date):
            if symbol in {"00700", "01528"}:
                return [{"close": 1, "open": 1, "high": 1, "low": 1, "volume": 1}] * 60
            return []

    monkeypatch.setattr(
        "app.jobs.strategy_jobs.market_data_provider",
        _FakeMarketDataProvider(),
    )

    symbols, meta = await _probe_hk_historical_ready_symbols(
        symbols=["00700", "09988", "03690", "01528"],
        task_id="auto_cycle:test-run",
    )

    assert symbols == ["00700", "01528"]
    assert meta["hk_history_probe_applied"] is True
    assert meta["hk_history_ready_count"] == 2


def test_resolve_market_by_runtime_switches_hk_and_us_windows():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    hk_runtime = datetime(2026, 3, 13, 14, 8, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    us_runtime = datetime(2026, 3, 13, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)

    assert _resolve_market_by_runtime(hk_runtime) == "HK"
    assert _resolve_market_by_runtime(us_runtime) == "US"
