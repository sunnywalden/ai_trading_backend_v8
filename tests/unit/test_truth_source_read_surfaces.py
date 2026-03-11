from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers.autonomy import get_autonomy_status
from app.services.situational_awareness_service import SituationalAwarenessService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def fetchall(self):
        return []

    def scalars(self):
        return SimpleNamespace(all=lambda: [])


@pytest.mark.asyncio
async def test_situational_awareness_regime_block_uses_truth_source(monkeypatch):
    svc = SituationalAwarenessService()

    monkeypatch.setattr(
        "app.services.truth_source_service.truth_source_service.get_regime_truth_snapshot",
        AsyncMock(
            return_value={
                "regime": "HIGH_VOL",
                "confidence": 0.73,
                "var_multiplier": 1.2,
                "source": "REDIS_RUNTIME",
            }
        ),
    )

    block = await svc._get_regime_block(db=AsyncMock())

    assert block.regime_type == "HIGH_VOL"
    assert block.confidence == pytest.approx(73.0)
    assert block.source == "REDIS_RUNTIME"


@pytest.mark.asyncio
async def test_autonomy_status_exposes_truth_sources(monkeypatch):
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(
        side_effect=[
            _ScalarResult(3),  # daily trades
            _ScalarResult([(SimpleNamespace(value="GENERATED"), 2)]),
            _ScalarResult(None),
            _ScalarResult(0),
            _ScalarResult([]),
        ]
    )

    # fetchall is used for grouped pipeline + cooldown query
    grouped_result = SimpleNamespace(fetchall=lambda: [(SimpleNamespace(value="GENERATED"), 2)])
    signals_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    fail_result = _ScalarResult(0)
    cooldown_result = SimpleNamespace(fetchall=lambda: [])
    fake_session.execute = AsyncMock(
        side_effect=[
            _ScalarResult(3),
            grouped_result,
            signals_result,
            fail_result,
            cooldown_result,
        ]
    )

    monkeypatch.setattr(
        "app.routers.autonomy._resolve_account_id",
        AsyncMock(return_value="acc-1"),
    )
    monkeypatch.setattr(
        "app.routers.autonomy._count_broker_filled_today",
        AsyncMock(return_value=4),
    )
    monkeypatch.setattr(
        "app.routers.autonomy.get_autonomy_level",
        AsyncMock(return_value="SEMI"),
    )
    monkeypatch.setattr(
        "app.services.truth_source_service.truth_source_service.get_positions_truth_snapshot",
        AsyncMock(return_value={"positions": {}, "positions_count": 7, "source": "POSITION_LIFECYCLE"}),
    )
    monkeypatch.setattr(
        "app.services.truth_source_service.truth_source_service.get_regime_truth_snapshot",
        AsyncMock(return_value={"regime": "BULL_TREND", "confidence": 0.88, "source": "REDIS_RUNTIME"}),
    )

    result = await get_autonomy_status(session=fake_session, current_user="user-1")

    assert result["positions_source"] == "POSITION_LIFECYCLE"
    assert result["positions_count_truth"] == 7
    assert result["regime_truth"]["regime"] == "BULL_TREND"
    assert result["regime_truth"]["source"] == "REDIS_RUNTIME"
