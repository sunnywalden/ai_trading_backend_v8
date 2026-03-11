from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.truth_source_service import TruthSourceService


class _ScalarResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_regime_truth_snapshot_prefers_redis_runtime(monkeypatch):
    svc = TruthSourceService()

    async def _fake_runtime():
        return {
            "regime": "BULL_TREND",
            "confidence": 0.82,
            "var_multiplier": 0.9,
        }

    monkeypatch.setattr(
        "app.services.regime_strategy_allocator.fetch_current_regime_from_redis",
        _fake_runtime,
    )

    snapshot = await svc.get_regime_truth_snapshot(db=AsyncMock())

    assert snapshot["regime"] == "BULL_TREND"
    assert snapshot["source"] == "REDIS_RUNTIME"
    assert snapshot["confidence"] == pytest.approx(0.82)
    assert snapshot["var_multiplier"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_regime_truth_snapshot_falls_back_to_db(monkeypatch):
    svc = TruthSourceService()

    async def _fake_runtime():
        return {"regime": "UNKNOWN", "confidence": 0.0, "var_multiplier": 1.0}

    monkeypatch.setattr(
        "app.services.regime_strategy_allocator.fetch_current_regime_from_redis",
        _fake_runtime,
    )

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(
        return_value=_ScalarResult(
            SimpleNamespace(regime="MEAN_REVERT", confidence=0.66)
        )
    )

    snapshot = await svc.get_regime_truth_snapshot(db=fake_db)

    assert snapshot["regime"] == "MEAN_REVERT"
    assert snapshot["source"] == "MARKET_REGIME_DB"
    assert snapshot["confidence"] == pytest.approx(0.66)


@pytest.mark.asyncio
async def test_positions_truth_snapshot_prefers_lifecycle(monkeypatch):
    svc = TruthSourceService()

    monkeypatch.setattr(
        "app.services.position_query_service.PositionQueryService.get_active_positions",
        AsyncMock(
            return_value=[
                {
                    "id": 101,
                    "symbol": "AAPL",
                    "open_qty": 12.0,
                    "avg_entry_price": 188.5,
                    "status": "ACTIVE",
                }
            ]
        ),
    )

    snapshot = await svc.get_positions_truth_snapshot(db=AsyncMock(), account_id="acc-1")

    assert snapshot["source"] == "POSITION_LIFECYCLE"
    assert snapshot["positions_count"] == 1
    assert snapshot["positions"]["AAPL"]["qty"] == pytest.approx(12.0)
    assert snapshot["positions"]["AAPL"]["truth_source"] == "POSITION_LIFECYCLE"


@pytest.mark.asyncio
async def test_positions_truth_snapshot_falls_back_to_position_monitor(monkeypatch):
    svc = TruthSourceService()

    monkeypatch.setattr(
        "app.services.position_query_service.PositionQueryService.get_active_positions",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.engine.position_monitor.PositionMonitor.get_positions_snapshot",
        AsyncMock(
            return_value={
                "MSFT": {
                    "qty": 5.0,
                    "avg_cost": 410.0,
                    "current_price": 412.0,
                }
            }
        ),
    )

    snapshot = await svc.get_positions_truth_snapshot(db=AsyncMock(), account_id="acc-1")

    assert snapshot["source"] == "POSITION_MONITOR"
    assert snapshot["positions_count"] == 1
    assert snapshot["positions"]["MSFT"]["qty"] == pytest.approx(5.0)
