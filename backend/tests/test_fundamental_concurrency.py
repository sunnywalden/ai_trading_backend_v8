import asyncio
import pytest

from app.services.fundamental_analysis_service import FundamentalAnalysisService


@pytest.mark.asyncio
async def test_batch_refresh_fundamentals_concurrent(monkeypatch):
    service = FundamentalAnalysisService()

    called = []

    async def fake_get_fundamental_data(symbol, force_refresh=True):
        called.append(symbol)
        # simulate network delay
        await asyncio.sleep(0.01)
        return {"overall_score": 60}

    monkeypatch.setattr(service, "get_fundamental_data", fake_get_fundamental_data)

    symbols = [f"SYM{i}" for i in range(10)]
    results = await service.batch_refresh_fundamentals(symbols)

    assert isinstance(results, dict)
    assert all(k in results for k in symbols)
    assert all(results[k] is True for k in symbols)
    # ensure all symbols were invoked
    assert set(called) == set(symbols)
