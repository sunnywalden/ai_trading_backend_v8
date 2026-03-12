import pytest

from app.services.risk_gate_service import RiskGateService


@pytest.mark.asyncio
async def test_risk_gate_uses_projected_post_trade_exposure_for_var_and_stress():
    svc = RiskGateService()
    positions = {
        "MSFT": {"qty": 100.0, "price": 100.0},
    }

    result = await svc.check(
        account_id="acc-1",
        symbol="AAPL",
        qty=200.0,
        side="BUY",
        current_equity=100000.0,
        current_positions=positions,
        daily_trades_today=0,
        daily_realized_pnl=0.0,
        signal_intent="OPEN",
        reference_price=100.0,
    )

    assert result.passed is True
    assert result.details["current_gross_exposure_pct"] == pytest.approx(0.1)
    assert result.details["projected_gross_exposure_pct"] == pytest.approx(0.3)
    assert result.details["projected_var_pct"] > result.details["current_var_pct"]
    assert result.details["projected_stress_loss_pct"] > result.details["current_stress_loss_pct"]


@pytest.mark.asyncio
async def test_risk_gate_uses_projected_symbol_exposure_for_short_entry_limit():
    svc = RiskGateService()

    result = await svc.check(
        account_id="acc-1",
        symbol="TSLA",
        qty=310.0,
        side="SELL",
        current_equity=100000.0,
        current_positions={},
        daily_trades_today=0,
        daily_realized_pnl=0.0,
        signal_intent="OPEN",
        reference_price=100.0,
    )

    assert result.passed is False
    assert "Position limit" in str(result.reason)
    assert result.details["projected_position_pct"] == pytest.approx(0.31)