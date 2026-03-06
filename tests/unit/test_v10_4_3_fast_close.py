import pytest
from types import SimpleNamespace
from typing import Any, cast

from app.engine.order_executor import OrderExecutor
from app.engine.signal_position_filter import Position, SignalPositionFilter
from app.models.trading_signal import SignalType
from app.services.risk_gate_service import RiskGateService
from app.services.signal_quality_funnel import SignalFunnelInput, SignalQualityFunnel


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


@pytest.mark.asyncio
async def test_order_executor_uses_actual_position_for_exit_and_flips_direction():
    executor = object.__new__(OrderExecutor)

    class _MarketProvider:
        async def get_current_price(self, symbol: str) -> float:
            return 100.0

        async def get_lot_size(self, symbol: str) -> int:
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

    params = await OrderExecutor._calculate_order_params(executor, cast(Any, signal), 100000)

    assert params["quantity"] == 137
    assert params["direction"] == "SHORT"
