from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.broker.factory import make_option_broker_client
from app.services.benchmark_service import BenchmarkService
from app.services.market_hotspot_service import MarketHotspotService


@pytest.mark.asyncio
async def test_market_hotspots_do_not_fallback_to_mock_when_disabled(monkeypatch):
    class _FakeCache:
        async def get(self, key):
            return None

        async def set(self, key, value, expire=None):
            return None

    monkeypatch.setattr("app.services.market_hotspot_service.cache", _FakeCache())
    monkeypatch.setattr("app.services.market_hotspot_service.settings.RUNTIME_ALLOW_MOCK_DATA", False)
    async def _fake_fetch_from_news_api(self):
        return []

    monkeypatch.setattr(MarketHotspotService, "_fetch_from_news_api", _fake_fetch_from_news_api)

    service = MarketHotspotService()
    result = await service.get_latest_hotspots(force_refresh=True)

    assert result == []


@pytest.mark.asyncio
async def test_benchmark_service_returns_empty_when_mock_disabled(monkeypatch):
    class _FakeCache:
        async def get(self, key):
            return None

        async def set(self, key, value, expire=None):
            return None

    monkeypatch.setattr("app.services.benchmark_service.cache", _FakeCache())
    monkeypatch.setattr("app.services.benchmark_service.settings.RUNTIME_ALLOW_MOCK_DATA", False)
    monkeypatch.setattr(
        "app.services.benchmark_service.make_option_broker_client",
        lambda: (_ for _ in ()).throw(RuntimeError("no broker")),
    )

    service = BenchmarkService(session=cast(Any, SimpleNamespace()))
    returns = await service.get_benchmark_returns("SPY", days=10)

    assert returns == []


def test_make_option_broker_client_raises_when_dummy_fallback_disabled(monkeypatch):
    monkeypatch.setattr("app.broker.factory._broker_instance", None)
    monkeypatch.setattr("app.broker.factory.settings.TIGER_PRIVATE_KEY_PATH", None)
    monkeypatch.setattr("app.broker.factory.settings.TIGER_ID", None)
    monkeypatch.setattr("app.broker.factory.settings.RUNTIME_ALLOW_DUMMY_BROKER", False)

    with pytest.raises(RuntimeError, match="dummy broker fallback is disabled"):
        make_option_broker_client()
