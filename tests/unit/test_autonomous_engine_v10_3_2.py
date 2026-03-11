import asyncio
from math import isclose
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import configure_mappers

from app.models.execution_intent import AutonomousExecutionIntent
from app.models.strategy import Strategy, StrategyRun  # noqa: F401
from app.models.trading_signal import SignalSource, SignalStatus, SignalType, TradingSignal
from app.services.autonomous_engine import AutonomousEngine

configure_mappers()


@pytest.mark.asyncio
async def test_execution_intent_idempotency_key_unique_enforced():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(AutonomousExecutionIntent.__table__.create)

    ae = AutonomousEngine()
    signal = {"id": 1, "signal_id": "sig-001", "symbol": "AAPL"}
    decision = {"symbol": "AAPL", "action": "BUY", "qty": 10}

    async with session_factory() as session:
        first = await ae._create_execution_intent(
            db=session,
            account_id="acc-1",
            signal=signal,
            decision=decision,
            status="PENDING",
            reason="unit-test",
        )
        second = await ae._create_execution_intent(
            db=session,
            account_id="acc-1",
            signal=signal,
            decision=decision,
            status="PENDING",
            reason="unit-test-duplicate",
        )

    await engine.dispose()

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_ai_decide_abs_shares_mode_fallback_uses_absolute_quantity(
    monkeypatch,
):
    ae = AutonomousEngine()

    async def _fake_call_ai(*args, **kwargs):
        await asyncio.sleep(0)
        return {
            "action": "HOLD",
            "symbol": "AAPL",
            "qty": 0,
            "reasoning": "mock hold",
        }

    monkeypatch.setattr(ae, "_call_ai", _fake_call_ai)

    signal = {
        "id": 10,
        "signal_id": "sig-abs-qty",
        "symbol": "AAPL",
        "signal_type": "ENTRY",
        "direction": "LONG",
        "confidence": 0.92,
        "quantity_mode": "ABS_SHARES",
        "quantity_value": 12,
    }
    positions = {
        "AAPL": {"market_price": 100.0}
    }

    decision = await ae._ai_decide(
        signal=signal,
        positions=positions,
        equity=100000.0,
    )

    assert decision["action"] == "BUY"
    assert float(decision["qty"]) == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_execute_order_uses_hard_control_payload(monkeypatch):
    ae = AutonomousEngine()
    captured: dict[str, Any] = {}

    class _FakeOrderService:
        def __init__(self, _session):
            self._session = _session

        async def submit_order(self, account_id: str, payload: dict):
            await asyncio.sleep(0)
            captured["account_id"] = account_id
            captured["payload"] = payload
            return SimpleNamespace(order_id="ord-hard-1")

    monkeypatch.setattr(
        "app.services.order_service.OrderService",
        _FakeOrderService,
    )
    monkeypatch.setattr(
        "app.core.market_hours.is_symbol_market_active",
        lambda _symbol: True,
    )

    with patch(
        (
            "app.services.execution_policy_service.execution_policy_service."
            "build_live_execution_controls_with_feedback"
        ),
        AsyncMock(return_value={
            "control_state": {"enabled": True, "mode": "HARD_CONTROL"},
            "policy": {
                "urgency": "LOW",
                "algo_type": "LIMIT",
            },
            "pretrade_cost": {"total_expected_cost_bps": 22.0},
            "requested_algo": "MARKET",
            "effective_algo": "LIMIT",
            "broker_order_type": "LMT",
            "limit_price": 123.45,
            "budget_breached": True,
        }),
    ):
        order_id = await ae._execute_order(
            "acc-1",
            {
                "symbol": "AAPL",
                "action": "BUY",
                "qty": 10,
                "algo": "MARKET",
                "ref_price": 123.0,
            },
            cast(Any, SimpleNamespace()),
        )

    assert order_id == "ord-hard-1"
    assert captured["account_id"] == "acc-1"
    assert captured["payload"]["order_type"] == "LMT"
    assert isclose(captured["payload"]["limit_price"], 123.45, rel_tol=1e-9)
    assert captured["payload"]["execution_control_mode"] == "HARD_CONTROL"


def test_build_signal_funnel_input_prefers_canonical_signal_payload():
    ae = AutonomousEngine()
    signal = {
        "id": 1,
        "symbol": "AAPL",
        "signal_type": "ENTRY",
        "direction": "LONG",
        "signal_strength": 88.0,
        "confidence": 0.88,
        "extra_metadata": {
            "signal_payload": {
                "version": "v10.5.4",
                "origin_mode": "REAL",
                "dimensions": {
                    "aligned_count": 6,
                    "aligned_dims": ["technical", "fundamental", "macro", "options", "flow", "sentiment"],
                    "opposing_dims": [],
                    "neutral_dims": [],
                    "adv_usd": 12_000_000,
                    "market_cap": 5_000_000_000,
                    "dimensions": [
                        {"name": "technical", "direction": 1, "score": 95},
                        {"name": "fundamental", "direction": 1, "score": 90},
                        {"name": "macro", "direction": 1, "score": 88},
                        {"name": "options", "direction": 1, "score": 86},
                    ],
                    "macro_score": 88,
                    "options_score": 86,
                },
                "quality_inputs": {
                    "historical_ic": 0.13,
                    "timing_quality": 0.81,
                },
            },
            "aligned_count": 1,
            "aligned_dims": ["legacy"],
        },
        "factor_scores": {"aligned_count": 2, "aligned_dims": ["older"]},
    }

    funnel_input = ae._build_signal_funnel_input(signal, "BULL_TREND")

    assert funnel_input.aligned_count == 6
    assert funnel_input.aligned_dims == ["technical", "fundamental", "macro", "options", "flow", "sentiment"]
    assert funnel_input.historical_ic == pytest.approx(0.13)
    assert funnel_input.timing_quality == pytest.approx(0.81)


@pytest.mark.asyncio
async def test_fetch_pending_signals_skips_synthetic_non_closing():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Strategy.__table__.create)
        await conn.run_sync(StrategyRun.__table__.create)
        await conn.run_sync(TradingSignal.__table__.create)

    ae = AutonomousEngine()

    async with session_factory() as session:
        session.add_all(
            [
                TradingSignal(
                    signal_id="sig-real-1",
                    signal_type=SignalType.ENTRY,
                    signal_source=SignalSource.STRATEGY,
                    signal_origin_mode="REAL",
                    status=SignalStatus.VALIDATED,
                    symbol="AAPL",
                    direction="LONG",
                    signal_strength=90.0,
                    confidence=0.9,
                    account_id="acc-1",
                    user_id="u-1",
                    extra_metadata={
                        "signal_payload": {
                            "version": "v10.5.4",
                            "origin_mode": "REAL",
                            "dimensions": {"aligned_count": 4, "aligned_dims": ["technical"]},
                        }
                    },
                    priority=90,
                ),
                TradingSignal(
                    signal_id="sig-syn-1",
                    signal_type=SignalType.ENTRY,
                    signal_source=SignalSource.STRATEGY,
                    signal_origin_mode="SYNTHETIC",
                    status=SignalStatus.VALIDATED,
                    symbol="MSFT",
                    direction="LONG",
                    signal_strength=95.0,
                    confidence=0.95,
                    account_id="acc-1",
                    user_id="u-1",
                    extra_metadata={
                        "signal_payload": {
                            "version": "v10.5.4",
                            "origin_mode": "SYNTHETIC",
                            "dimensions": {"aligned_count": 6, "aligned_dims": ["technical", "macro"]},
                        }
                    },
                    priority=95,
                ),
            ]
        )
        await session.commit()

        pending = await ae._fetch_pending_signals("acc-1", session)

    await engine.dispose()

    assert [row["signal_id"] for row in pending] == ["sig-real-1"]
    assert pending[0]["signal_origin_mode"] == "REAL"
