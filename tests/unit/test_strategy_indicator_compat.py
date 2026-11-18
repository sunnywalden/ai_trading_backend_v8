from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.strategies.bollinger_bands import BollingerBandsMeanReversion
from app.engine.strategies.breakout_momentum import BreakoutMomentum
from app.engine.strategies.golden_cross import GoldenCross


class _FakeExecResult:
    def __init__(self, item: Any):
        self._item = item

    def scalars(self):
        return self

    def first(self):
        return self._item


@pytest.mark.asyncio
async def test_golden_cross_reads_flat_indicator_columns(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_FakeExecResult(
            SimpleNamespace(ma_50=120.0, ma_200=100.0, macd=2.0, macd_signal=1.0)
        )
    )

    class _FakeMarketDataProvider:
        async def get_latest_price(self, symbol: str) -> float:
            return 125.0

    monkeypatch.setattr(
        "app.engine.strategies.golden_cross.market_data_provider",
        _FakeMarketDataProvider(),
    )

    strategy = GoldenCross(params={}, session=cast(Any, session))
    signals = await strategy.generate_signals(universe=["00700"])

    assert len(signals) == 1
    assert signals[0]["direction"] == "BUY"
    assert signals[0]["metadata"]["sma_50"] == 120.0


@pytest.mark.asyncio
async def test_breakout_momentum_reads_flat_atr_column(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeExecResult(SimpleNamespace(atr_14=3.5)))

    class _FakeMarketDataProvider:
        async def get_historical_prices(self, symbol, start_date, end_date):
            prices = []
            for i in range(60):
                close = 100.0 + i
                high = 101.0 + i
                volume = 1_000_000 + i * 5_000
                if i == 59:
                    close = 170.0
                    high = 171.0
                    volume = 2_500_000
                prices.append(
                    {
                        "close": close,
                        "high": high,
                        "low": 99.0 + i,
                        "volume": volume,
                    }
                )
            return prices

    monkeypatch.setattr(
        "app.engine.strategies.breakout_momentum.market_data_provider",
        _FakeMarketDataProvider(),
    )

    strategy = BreakoutMomentum(params={"lookback_days": 20, "volume_multiplier": 1.1}, session=cast(Any, session))
    signals = await strategy.generate_signals(universe=["00700"])

    assert len(signals) == 1
    assert signals[0]["metadata"]["atr"] == 3.5


@pytest.mark.asyncio
async def test_breakout_momentum_can_compute_atr_without_cached_indicator(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeExecResult(SimpleNamespace(atr_14=0.0)))

    class _FakeMarketDataProvider:
        async def get_historical_prices(self, symbol, start_date, end_date):
            prices = []
            for i in range(60):
                close = 100.0 + i
                high = close + 2.0
                low = close - 2.0
                volume = 1_000_000 + i * 5_000
                if i == 59:
                    close = 170.0
                    high = 174.0
                    low = 166.0
                    volume = 2_500_000
                prices.append(
                    {
                        "close": close,
                        "high": high,
                        "low": low,
                        "volume": volume,
                    }
                )
            return prices

    monkeypatch.setattr(
        "app.engine.strategies.breakout_momentum.market_data_provider",
        _FakeMarketDataProvider(),
    )

    strategy = BreakoutMomentum(params={"lookback_days": 20, "volume_multiplier": 1.1}, session=cast(Any, session))
    signals = await strategy.generate_signals(universe=["00700"])

    assert len(signals) == 1
    assert signals[0]["metadata"]["atr"] > 0


@pytest.mark.asyncio
async def test_bollinger_strategy_reads_flat_band_columns(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_FakeExecResult(
            SimpleNamespace(bb_upper=110.0, bb_middle=100.0, bb_lower=90.0)
        )
    )

    class _FakeMarketDataProvider:
        async def get_latest_price(self, symbol: str) -> float:
            return 88.0

    monkeypatch.setattr(
        "app.engine.strategies.bollinger_bands.market_data_provider",
        _FakeMarketDataProvider(),
    )

    strategy = BollingerBandsMeanReversion(params={}, session=cast(Any, session))
    signals = await strategy.generate_signals(universe=["00700"])

    assert len(signals) == 1
    assert signals[0]["direction"] == "BUY"
    assert signals[0]["metadata"]["lower_band"] == 90.0
