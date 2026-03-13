from __future__ import annotations

from unittest.mock import AsyncMock
from typing import Any, cast

import pandas as pd
import pytest

from app.data.hub import DataHub
from app.providers.market_data_provider import MarketDataProvider


def _reset_market_data_provider_budget_state() -> None:
    MarketDataProvider._tiger_historical_denied_cache = {}
    MarketDataProvider._tiger_historical_occupied_symbols = set()
    MarketDataProvider._tiger_historical_occupied_updated_at = 0.0
    MarketDataProvider._tiger_historical_occupied_authoritative = False
    MarketDataProvider._class_bars_cache = {}


def _permission_error_message(requested: str = "00002") -> str:
    return (
        "code=4 msg=4000:permission denied(Based on a comprehensive assessment of the user's capital and trading volume, "
        "you currently have access to 200 symbols of historical market data, occupied symbols: "
        f"[AAPL, 00700HK, 09988, {requested}])"
    )


def test_market_data_provider_parses_occupied_symbols_with_hk_normalization():
    _reset_market_data_provider_budget_state()
    provider = MarketDataProvider()

    provider._remember_tiger_historical_denial("00001", _permission_error_message())

    assert "00700" in MarketDataProvider._tiger_historical_occupied_symbols
    assert "00700HK" not in MarketDataProvider._tiger_historical_occupied_symbols
    assert provider._should_attempt_tiger_historical("00700HK") is True
    assert provider._should_attempt_tiger_historical("00001") is False


def test_market_data_provider_success_does_not_create_authoritative_budget_snapshot():
    _reset_market_data_provider_budget_state()
    provider = MarketDataProvider()

    provider._remember_tiger_historical_success("AAPL")

    assert MarketDataProvider._tiger_historical_occupied_authoritative is False
    assert provider._should_attempt_tiger_historical("MSFT") is True


@pytest.mark.asyncio
async def test_market_data_provider_skips_tiger_for_known_non_occupied_symbol(monkeypatch):
    _reset_market_data_provider_budget_state()
    provider = MarketDataProvider()
    provider.primary_source = "yfinance"
    provider.fallback_source = "tiger"
    provider._tiger_quote_client = cast(Any, object())

    provider._remember_tiger_historical_denial("00001", _permission_error_message())

    tiger_mock = AsyncMock(return_value=pd.DataFrame({"Close": [1.0]}))
    yahoo_mock = AsyncMock(return_value=pd.DataFrame())
    cache_get = AsyncMock(return_value=None)
    cache_set = AsyncMock(return_value=True)
    monkeypatch.setattr(provider, "_get_tiger_bars", tiger_mock)
    monkeypatch.setattr(provider, "_get_yahoo_data_with_retry", yahoo_mock)
    monkeypatch.setattr("app.providers.market_data_provider.cache.get", cache_get)
    monkeypatch.setattr("app.providers.market_data_provider.cache.set", cache_set)

    result = await provider.get_historical_data("00001", period="1y", interval="1d")

    assert result.empty
    tiger_mock.assert_not_awaited()
    yahoo_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_market_data_provider_uses_redis_cached_bars_before_external(monkeypatch):
    _reset_market_data_provider_budget_state()
    provider = MarketDataProvider()
    provider._tiger_quote_client = cast(Any, object())

    cached_df = pd.DataFrame(
        [{"Open": 1.0, "High": 1.2, "Low": 0.9, "Close": 1.1, "Volume": 1000.0}],
        index=[pd.Timestamp("2026-03-12T00:00:00")],
    )
    cache_get = AsyncMock(return_value=provider._serialize_bars_df(cached_df))
    cache_set = AsyncMock(return_value=True)
    tiger_mock = AsyncMock(return_value=pd.DataFrame())

    monkeypatch.setattr("app.providers.market_data_provider.cache.get", cache_get)
    monkeypatch.setattr("app.providers.market_data_provider.cache.set", cache_set)
    monkeypatch.setattr(provider, "_get_tiger_bars", tiger_mock)

    result = await provider.get_historical_data("AAPL", period="6mo", interval="1d")

    assert not result.empty
    assert float(result.iloc[-1]["Close"]) == pytest.approx(1.1)
    tiger_mock.assert_not_awaited()
    cache_get.assert_awaited()
    cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_data_provider_refresh_writes_redis_bars_cache(monkeypatch):
    _reset_market_data_provider_budget_state()
    provider = MarketDataProvider()
    provider._tiger_quote_client = cast(Any, object())

    fresh_df = pd.DataFrame(
        [{"Open": 2.0, "High": 2.2, "Low": 1.9, "Close": 2.1, "Volume": 2000.0}],
        index=[pd.Timestamp("2026-03-12T00:00:00")],
    )
    cache_get = AsyncMock(return_value=None)
    cache_set = AsyncMock(return_value=True)
    tiger_mock = AsyncMock(return_value=fresh_df)

    monkeypatch.setattr("app.providers.market_data_provider.cache.get", cache_get)
    monkeypatch.setattr("app.providers.market_data_provider.cache.set", cache_set)
    monkeypatch.setattr(provider, "_get_tiger_bars", tiger_mock)

    result = await provider.get_historical_data("MSFT", period="6mo", interval="1d", force_refresh=True)

    assert not result.empty
    tiger_mock.assert_awaited_once()
    cache_set.assert_awaited()


@pytest.mark.asyncio
async def test_market_data_provider_uses_cached_key_statistics_before_live_fetch(monkeypatch):
    provider = MarketDataProvider()
    cache_get = AsyncMock(return_value={"roe": 0.21, "debt_to_equity": 18.0})
    cache_set = AsyncMock(return_value=True)
    live_call = AsyncMock(side_effect=AssertionError("should not fetch live when cache exists"))

    monkeypatch.setattr("app.providers.market_data_provider.cache.get", cache_get)
    monkeypatch.setattr("app.providers.market_data_provider.cache.set", cache_set)
    monkeypatch.setattr(provider, "_run_external", live_call)

    stats = await provider.get_key_statistics("AAPL")

    assert stats["roe"] == pytest.approx(0.21)
    live_call.assert_not_awaited()
    cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_data_provider_cache_only_key_statistics_returns_empty_without_cache(monkeypatch):
    provider = MarketDataProvider()
    cache_get = AsyncMock(return_value=None)
    live_call = AsyncMock(side_effect=AssertionError("cache_only should not fetch live"))

    monkeypatch.setattr("app.providers.market_data_provider.cache.get", cache_get)
    monkeypatch.setattr(provider, "_run_external", live_call)

    stats = await provider.get_key_statistics("MSFT", cache_only=True)

    assert stats == {}
    live_call.assert_not_awaited()


def test_data_hub_permission_budget_allows_only_occupied_symbols():
    hub = DataHub()
    hub._record_tiger_ohlcv_failure(RuntimeError(_permission_error_message()), "00001")

    assert hub._should_attempt_tiger_ohlcv_for_symbol("00700HK") is True
    assert hub._should_attempt_tiger_ohlcv_for_symbol("00001") is False
