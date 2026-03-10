from datetime import date

import pandas as pd
import pytest

from app.data.hub import DataHub


_HK_PERMISSION_ERROR = (
    "code=4 msg=4000:permission denied(Current user and device do not have permissions in the HK market)"
)


@pytest.mark.asyncio
async def test_get_quote_hk_permission_denied_falls_back_and_skips_future_tiger_calls(monkeypatch):
    hub = DataHub()
    calls = {"tiger": 0, "yf": 0}

    async def _fake_tiger_quote(symbol: str) -> dict:
        calls["tiger"] += 1
        raise RuntimeError(_HK_PERMISSION_ERROR)

    async def _fake_fetch_quote(source: str, symbol: str) -> dict:
        calls["yf"] += 1
        assert source == "yfinance"
        assert symbol == "1393.HK"
        return {"symbol": symbol, "price": 0.063, "source": source}

    monkeypatch.setattr(hub, "_tiger_quote", _fake_tiger_quote)
    monkeypatch.setattr(hub, "_fetch_quote", _fake_fetch_quote)

    first = await hub.get_quote("01393")
    second = await hub.get_quote("01393")

    assert first["price"] == pytest.approx(0.063)
    assert second["price"] == pytest.approx(0.063)
    assert calls == {"tiger": 1, "yf": 2}
    assert hub._hk_tiger_permission_denied is True


@pytest.mark.asyncio
async def test_get_ohlcv_hk_permission_denied_falls_back_and_skips_future_tiger_calls(monkeypatch):
    hub = DataHub()
    calls = {"tiger": 0, "yf": 0}
    expected = pd.DataFrame(
        [{"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000}],
        index=[date(2026, 3, 10)],
    )

    async def _fake_tiger_ohlcv(symbol: str, start: date, end: date, interval: str) -> pd.DataFrame:
        calls["tiger"] += 1
        raise RuntimeError(_HK_PERMISSION_ERROR)

    async def _fake_fetch_ohlcv(
        source: str,
        symbol: str,
        start: date,
        end: date,
        interval: str,
    ) -> pd.DataFrame:
        calls["yf"] += 1
        assert source == "yfinance"
        assert symbol == "1393.HK"
        return expected

    monkeypatch.setattr(hub, "_tiger_ohlcv", _fake_tiger_ohlcv)
    monkeypatch.setattr(hub, "_fetch_ohlcv", _fake_fetch_ohlcv)

    first = await hub.get_ohlcv("01393", date(2026, 3, 1), date(2026, 3, 10))
    second = await hub.get_ohlcv("01393", date(2026, 3, 1), date(2026, 3, 10))

    assert not first.empty
    assert not second.empty
    assert calls == {"tiger": 1, "yf": 2}
    assert hub._hk_tiger_permission_denied is True