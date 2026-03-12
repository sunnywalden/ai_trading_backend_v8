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


@pytest.mark.asyncio
async def test_positions_read_model_prefers_broker_live_when_mismatch(monkeypatch):
    svc = TruthSourceService()

    monkeypatch.setattr(
        svc,
        "_get_lifecycle_position_rows",
        AsyncMock(
            return_value=[
                {"symbol": "ORCL", "open_qty": 560.0, "avg_entry_price": 200.0, "status": "ACTIVE"},
                {"symbol": "MSFT", "open_qty": 100.0, "avg_entry_price": 300.0, "status": "ACTIVE"},
            ]
        ),
    )
    monkeypatch.setattr(
        svc,
        "_get_broker_position_snapshot",
        AsyncMock(
            return_value={
                "AMD": {"qty": 10.0, "avg_cost": 120.0, "current_price": 125.0, "unrealized_pnl_pct": 0.0417},
                "PLTR": {"qty": 8.0, "avg_cost": 30.0, "current_price": 31.5, "unrealized_pnl_pct": 0.05},
            }
        ),
    )

    snapshot = await svc.get_positions_read_model(db=AsyncMock(), account_id="acc-1")

    assert snapshot["source"] == "BROKER_LIVE_OVERRIDE"
    assert snapshot["active_positions"] == 2
    assert snapshot["mismatch_detected"] is True
    assert set(snapshot["mismatch_symbols"]) == {"AMD", "MSFT", "ORCL", "PLTR"}
    assert [row["symbol"] for row in snapshot["items"]] == ["AMD", "PLTR"]


@pytest.mark.asyncio
async def test_positions_read_model_uses_lifecycle_when_broker_empty(monkeypatch):
    svc = TruthSourceService()

    monkeypatch.setattr(
        svc,
        "_get_lifecycle_position_rows",
        AsyncMock(
            return_value=[
                {"symbol": "QCOM", "open_qty": 50.0, "avg_entry_price": 180.0, "status": "ACTIVE"},
            ]
        ),
    )
    monkeypatch.setattr(
        svc,
        "_get_broker_position_snapshot",
        AsyncMock(return_value={}),
    )

    snapshot = await svc.get_positions_read_model(db=AsyncMock(), account_id="acc-1")

    assert snapshot["source"] == "POSITION_LIFECYCLE_FALLBACK"
    assert snapshot["active_positions"] == 1
    assert snapshot["items"][0]["symbol"] == "QCOM"
