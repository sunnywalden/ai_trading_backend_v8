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
    monkeypatch.setattr(provider, "_get_tiger_bars", tiger_mock)
    monkeypatch.setattr(provider, "_get_yahoo_data_with_retry", yahoo_mock)

    result = await provider.get_historical_data("00001", period="1y", interval="1d")

    assert result.empty
    tiger_mock.assert_not_awaited()
    yahoo_mock.assert_awaited_once()


def test_data_hub_permission_budget_allows_only_occupied_symbols():
    hub = DataHub()
    hub._record_tiger_ohlcv_failure(RuntimeError(_permission_error_message()), "00001")

    assert hub._should_attempt_tiger_ohlcv_for_symbol("00700HK") is True
    assert hub._should_attempt_tiger_ohlcv_for_symbol("00001") is False
