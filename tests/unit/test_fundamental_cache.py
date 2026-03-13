from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.jobs import data_refresh_jobs
from app.services.fundamental_analysis_service import FundamentalAnalysisService


@pytest.mark.asyncio
async def test_get_fundamental_data_prefers_redis_cache(monkeypatch):
    service = FundamentalAnalysisService()
    cached = {
        "symbol": "AAPL",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "pe_ratio": 20.0,
        "pb_ratio": 10.0,
        "peg_ratio": 1.5,
        "beta": 1.1,
        "roe": 25.0,
        "roa": 15.0,
        "profit_margin": 22.0,
        "revenue_growth": 12.0,
        "earnings_growth": 10.0,
        "current_ratio": 1.5,
        "debt_to_equity": 0.4,
        "valuation_score": 70.0,
        "profitability_score": 82.0,
        "growth_score": 68.0,
        "health_score": 77.0,
        "overall_score": 74.25,
        "timestamp": "2026-03-13T00:00:00",
        "fiscal_date": "2026-03-13",
    }

    async def fake_redis_get(symbol):
        return SimpleNamespace(**cached)

    monkeypatch.setattr(service, "_get_cached_result_from_redis", fake_redis_get)

    result = await service.get_fundamental_data("AAPL")

    assert result is not None
    assert result.symbol == "AAPL"
    assert result.overall_score == pytest.approx(74.25)


@pytest.mark.asyncio
async def test_refresh_fundamental_data_job_includes_active_symbol_pool(monkeypatch):
    called_symbols: list[str] = []

    class _FakeFundamentalService:
        async def batch_refresh_fundamentals(self, symbols):
            called_symbols.extend(symbols)
            return {symbol: True for symbol in symbols}

    class _FakeBroker:
        async def get_account_id(self):
            return "acct"

        async def list_underlying_positions(self, account_id):
            return [SimpleNamespace(symbol="AAPL"), SimpleNamespace(symbol="00700")]

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_collect_symbols(session):
        return ["MSFT", "00700", "AAPL", "NVDA"]

    monkeypatch.setattr(
        "app.services.fundamental_analysis_service.FundamentalAnalysisService",
        _FakeFundamentalService,
    )
    monkeypatch.setattr(
        data_refresh_jobs,
        "make_option_broker_client",
        lambda: _FakeBroker(),
    )
    monkeypatch.setattr(
        data_refresh_jobs,
        "_collect_symbols_for_historical_refresh",
        fake_collect_symbols,
    )
    monkeypatch.setattr(
        data_refresh_jobs,
        "_get_session",
        lambda: _FakeSession(),
    )

    result = await data_refresh_jobs.refresh_fundamental_data_job()

    assert result is None or result.get("success") is not False
    assert called_symbols[:4] == ["AAPL", "00700", "MSFT", "NVDA"]
    assert len(called_symbols) == len(set(called_symbols))
