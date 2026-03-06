from types import SimpleNamespace

import pytest

from app.engine.performance_analyzer import PerformanceAnalyzer


class _FakeScalarResult:
    def __init__(self, payload):
        self._payload = payload

    def all(self):
        return self._payload

    def first(self):
        return self._payload


class _FakeResult:
    def __init__(self, payload):
        self._payload = payload

    def scalars(self):
        return _FakeScalarResult(self._payload)


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)

    async def execute(self, _stmt):
        if not self._responses:
            raise AssertionError("No more fake responses configured")
        return _FakeResult(self._responses.pop(0))


@pytest.mark.asyncio
async def test_evaluate_daily_performance_handles_null_equity_returns():
    equity_snapshot = SimpleNamespace(
        total_equity=100000,
        realized_pnl=1250,
        daily_return=None,
        cumulative_return=None,
    )
    analyzer = PerformanceAnalyzer(_FakeSession([[], equity_snapshot]))

    result = await analyzer.evaluate_daily_performance(account_id="acc-1")

    assert result["total_equity"] == 100000.0
    assert result["daily_pnl"] == 1250.0
    assert result["daily_return"] == 0
    assert result["cumulative_return"] == 0