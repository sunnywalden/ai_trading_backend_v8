from __future__ import annotations

from unittest.mock import AsyncMock

import pandas as pd
import pytest

from app.providers.market_data_provider import MarketDataProvider


@pytest.mark.asyncio
async def test_hk_historical_data_can_fallback_to_yahoo_after_tiger_miss(monkeypatch):
    provider = MarketDataProvider()
    provider.primary_source = "tiger"
    provider.fallback_source = "yfinance"
    provider._tiger_quote_client = object()
    provider._get_tiger_bars = AsyncMock(return_value=pd.DataFrame())
    provider._get_yahoo_data_with_retry = AsyncMock(
        return_value=pd.DataFrame(
            [{"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000}],
            index=pd.to_datetime(["2026-03-13"]),
        )
    )
    provider._wait_for_rate_limit = AsyncMock(return_value=None)

    result = await provider.get_historical_data("00700", period="1mo", interval="1d")

    assert not result.empty
    provider._get_yahoo_data_with_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_hk_current_price_can_fallback_to_yahoo_after_tiger_miss(monkeypatch):
    provider = MarketDataProvider()
    provider.primary_source = "tiger"
    provider.fallback_source = "yfinance"
    provider._tiger_quote_client = object()
    provider._get_tiger_price_single = AsyncMock(return_value=0.0)
    provider._get_yahoo_price_robust = AsyncMock(return_value=321.5)

    result = await provider.get_current_price("00700")

    assert result == 321.5
    provider._get_yahoo_price_robust.assert_awaited_once()
