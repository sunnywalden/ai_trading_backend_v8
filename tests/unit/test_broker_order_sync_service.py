from app.services.broker_order_sync_service import (
    _derive_reconciled_stage,
    _extract_live_position_symbols,
    _is_plan_reconcile_candidate,
    _should_apply_stage_update,
)
from app.models.trading_signal import SignalStatus


class _SignalStub:
    def __init__(self, *, symbol: str, status: SignalStatus):
        self.symbol = symbol
        self.status = status


def test_reconcile_candidate_excludes_post_trade_plans():
    assert _is_plan_reconcile_candidate(7, "AUTO_EXECUTING") is True
    assert _is_plan_reconcile_candidate(8, "ACTIVE") is True
    assert _is_plan_reconcile_candidate(None, "EXECUTED") is True

    assert _is_plan_reconcile_candidate(12, "EXECUTED") is False
    assert _is_plan_reconcile_candidate(13, "EXECUTED") is False
    assert _is_plan_reconcile_candidate(14, "EXECUTED") is False


def test_should_apply_stage_update_never_regresses_post_trade_stage():
    assert _should_apply_stage_update(None, 12) is True
    assert _should_apply_stage_update(8, 12) is True
    assert _should_apply_stage_update(13, 14) is True

    assert _should_apply_stage_update(13, 12) is False
    assert _should_apply_stage_update(14, 12) is False
    assert _should_apply_stage_update(16, 12) is False


def test_extract_live_position_symbols_filters_zero_qty_positions():
    raw_positions = [
        {"symbol": "AAPL", "quantity": 100},
        {"symbol": "TSLA", "qty": 0},
        type("Pos", (), {"symbol": "NVDA", "quantity": 20})(),
    ]

    assert _extract_live_position_symbols(raw_positions) == {"AAPL", "NVDA"}


def test_derive_reconciled_stage_moves_filled_entry_to_stage_9_when_position_exists():
    signal = _SignalStub(symbol="AAPL", status=SignalStatus.EXECUTED)

    assert _derive_reconciled_stage(signal, {"AAPL"}) == (9, "EXECUTED", "HELD")
    assert _derive_reconciled_stage(signal, set()) == (12, "EXECUTED", "CLOSED")


def test_derive_reconciled_stage_handles_terminal_failures():
    cancelled = _SignalStub(symbol="AAPL", status=SignalStatus.CANCELLED)
    rejected = _SignalStub(symbol="AAPL", status=SignalStatus.REJECTED)

    assert _derive_reconciled_stage(cancelled, {"AAPL"}) == (16, "REVOKED", "CLOSED")
    assert _derive_reconciled_stage(rejected, {"AAPL"}) == (16, "FAILED", "CLOSED")