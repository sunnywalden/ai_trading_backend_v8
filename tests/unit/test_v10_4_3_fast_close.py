import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.engine.order_executor import OrderExecutor
from app.engine.signal_position_filter import Position, SignalPositionFilter
from app.models.trading_signal import SignalType
from app.services.autonomous_engine import AutonomousEngine
from app.services.risk_gate_service import RiskGateService
from app.services.signal_quality_funnel import (SignalFunnelInput,
                                                SignalQualityFunnel,
                                                SignalQualityProfile,
                                                SignalQualityTier)


@pytest.mark.asyncio
async def test_risk_gate_allows_exit_during_circuit_breaker():
    gate = RiskGateService()

    result = await gate.check(
        account_id="acc-1",
        symbol="AAPL",
        qty=100,
        side="SELL",
        current_equity=100000,
        current_positions={"AAPL": {"qty": 100, "price": 100}},
        daily_trades_today=10,
        daily_realized_pnl=-6000,
        signal_intent="EXIT",
    )

    assert result.passed is True
    assert result.circuit_breaker is True
    assert result.details is not None
    assert result.details["bypass_reason"] == "closing_intent"


@pytest.mark.asyncio
async def test_risk_gate_daily_trade_limit_does_not_block_reduce():
    gate = RiskGateService()

    result = await gate.check(
        account_id="acc-1",
        symbol="AAPL",
        qty=25,
        side="SELL",
        current_equity=100000,
        current_positions={"AAPL": {"qty": 100, "price": 100}},
        daily_trades_today=999,
        daily_realized_pnl=0,
        signal_intent="REDUCE",
    )

    assert result.passed is True
    assert result.details is not None
    assert result.details["is_closing_intent"] is True
    assert result.details["var_check_skipped"] is True
    assert result.details["stress_check_skipped"] is True


def test_signal_position_filter_auto_adjusts_reduce_to_exit():
    filter_service = object.__new__(SignalPositionFilter)
    signal = SimpleNamespace(
        symbol="TSLA",
        direction="LONG",
        suggested_quantity=200,
        quantity_mode="ABS_SHARES",
        quantity_value=200,
        signal_type=SignalType.REDUCE,
        extra_metadata={},
    )
    position = Position(
        symbol="TSLA",
        qty=100,
        avg_cost=200,
        market_value=20000,
        unrealized_pnl=500,
    )

    result = SignalPositionFilter._filter_reduce_signal(filter_service, cast(Any, signal), position)

    assert result.passed is True
    assert signal.signal_type == SignalType.EXIT
    assert signal.suggested_quantity == 100
    assert signal.quantity_value == 100
    assert signal.extra_metadata["auto_adjusted_to_exit"] is True


def test_signal_quality_funnel_skips_layer2_for_closing_signals():
    funnel = SignalQualityFunnel()
    signal = SignalFunnelInput(
        signal_id=1,
        symbol="AAPL",
        signal_type="EXIT",
        direction="SHORT",
        regime="CRISIS",
    )

    reject = funnel._layer2_portfolio(
        signal=signal,
        regime_cfg={
            "MAX_CONCURRENT_POSITIONS": 0,
            "MAX_DAILY_SIGNALS": 0,
            "MAX_POSITION_CORRELATION": 0.0,
        },
        current_positions=10,
        daily_executed=10,
        is_closing=True,
    )

    assert reject is None


def test_signal_quality_funnel_allows_elite_signal_to_bypass_daily_quota():
    funnel = SignalQualityFunnel()
    signal = SignalFunnelInput(
        signal_id=2,
        symbol="MSFT",
        signal_type="ENTRY",
        direction="LONG",
        regime="BULL_TREND",
        composite_score=1.0,
        aligned_count=6,
        aligned_dims=["technical", "fundamental", "macro", "options", "flow", "sentiment"],
        historical_ic=1.0,
        timing_quality=1.0,
        macro_score=1.0,
        options_score=1.0,
        tech_direction=1,
        fundamental_direction=1,
    )

    quality_profile = funnel.preview_quality(signal)
    reject = funnel._layer2_portfolio(
        signal=signal,
        regime_cfg={
            "MAX_CONCURRENT_POSITIONS": 6,
            "MAX_DAILY_SIGNALS": 0,
            "MAX_POSITION_CORRELATION": 0.9,
        },
        current_positions=1,
        daily_executed=1,
        quality_profile=quality_profile,
    )

    assert quality_profile.tier == SignalQualityTier.ELITE
    assert quality_profile.quota_exempt is True
    assert reject is None


def test_autonomous_engine_ranks_by_execution_path_then_quality():
    engine = AutonomousEngine()
    signals = [
        {
            "id": 1,
            "symbol": "LOW",
            "signal_type": "ENTRY",
            "direction": "LONG",
            "confidence": 0.75,
            "priority": 1,
            "aligned_count": 3,
            "aligned_dims": ["technical", "macro", "flow"],
            "historical_ic": 0.4,
            "timing_quality": 0.5,
            "macro_score": 0.6,
            "options_score": 0.6,
        },
        {
            "id": 2,
            "symbol": "ELITE",
            "signal_type": "ENTRY",
            "direction": "LONG",
            "confidence": 1.0,
            "priority": 5,
            "aligned_count": 6,
            "aligned_dims": ["technical", "fundamental", "macro", "options", "flow", "sentiment"],
            "historical_ic": 1.0,
            "timing_quality": 1.0,
            "macro_score": 1.0,
            "options_score": 1.0,
            "dimensions": [
                {"name": "technical", "direction": 1, "score": 100},
                {"name": "fundamental", "direction": 1, "score": 100},
                {"name": "macro", "direction": 1, "score": 100},
                {"name": "options", "direction": 1, "score": 100},
            ],
        },
        {
            "id": 3,
            "symbol": "EXIT_NOW",
            "signal_type": "EXIT",
            "direction": "LONG",
            "confidence": 0.2,
            "priority": 0,
        },
    ]

    ranked = engine._rank_signals_for_processing(signals, "BULL_TREND")

    assert [item["symbol"] for item in ranked] == ["EXIT_NOW", "ELITE", "LOW"]
    assert ranked[0]["execution_path"] == "FAST_CLOSE"
    assert ranked[1]["signal_quality_tier"] == SignalQualityTier.ELITE
    assert ranked[1]["signal_quality_quota_exempt"] is True
    assert ranked[1]["signal_queue_rank"] == 2
    assert ranked[2]["signal_quality_tier"] in {SignalQualityTier.LOW, SignalQualityTier.MEDIUM}


@pytest.mark.asyncio
async def test_order_executor_uses_actual_position_for_exit_and_flips_direction():
    executor = object.__new__(OrderExecutor)

    class _MarketProvider:
        async def get_current_price(self, _symbol: str) -> float:
            await asyncio.sleep(0)
            return 100.0

        async def get_lot_size(self, _symbol: str) -> int:
            await asyncio.sleep(0)
            return 100

    executor.market_provider = cast(Any, _MarketProvider())

    signal = SimpleNamespace(
        symbol="0700.HK",
        direction="LONG",
        signal_type=SignalType.EXIT,
        suggested_quantity=0.3,
        quantity_value=0.3,
        suggested_price=100.0,
        stop_loss=None,
        take_profit=None,
        extra_metadata={
            "current_position": {
                "qty": 137,
                "price": 100.0,
            }
        },
    )

    params = await OrderExecutor._calculate_order_params(
        executor,
        cast(Any, signal),
        100000,
    )

    assert params["quantity"] == 137
    assert params["direction"] == "SHORT"


def test_order_executor_builds_execution_feedback_payload_for_exit_signal():
    signal = SimpleNamespace(
        account_id="acc-1",
        symbol="AAPL",
        direction="LONG",
        signal_type=SignalType.EXIT,
        suggested_price=100.0,
        suggested_quantity=50.0,
        executed_price=99.5,
        executed_quantity=50.0,
        created_at=datetime.now() - timedelta(seconds=2),
    )
    intent = SimpleNamespace(
        id=7,
        created_at=datetime.now() - timedelta(seconds=3),
    )
    resp = {
        "avg_fill_price": 99.4,
        "filled_quantity": 50.0,
        "order_type": "LIMIT",
    }

    payload = OrderExecutor._build_execution_feedback_payload(
        cast(Any, signal),
        intent,
        resp,
    )

    assert payload["intent_id"] == 7
    assert payload["direction"] == "SELL"
    assert payload["arrival_price"] == pytest.approx(100.0)
    assert payload["fill_price"] == pytest.approx(99.4)
    assert payload["algo_type"] == "LIMIT"
    assert payload["time_to_fill_ms"] > 0
