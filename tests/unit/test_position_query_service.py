from types import SimpleNamespace
from typing import Any, cast

from app.services.position_query_service import _pos_to_dict


def test_pos_to_dict_falls_back_to_current_position_fields():
    position = SimpleNamespace(
        id=1,
        account_id="DU123",
        symbol="AMD",
        thesis_key="default",
        status="ACTIVE",
        direction="LONG",
        total_qty=100.0,
        filled_qty=100.0,
        open_qty=100.0,
        closed_qty=0.0,
        avg_entry_price=10.5,
        realized_pnl=0.0,
        unrealized_pnl_pct=0.12,
        stop_loss_price=9.5,
        take_profit_price=12.0,
        max_holding_days=30,
        closing_reason=None,
        closing_source="AUTONOMOUS",
        exemption_active=0,
        exemption_reason="manual override",
        governance_flag="NORMAL",
        initial_signal_id=101,
        initial_signal_uid="sig-101",
        latest_plan_id=501,
        opened_at=None,
        closed_at=None,
        last_action_at=None,
        created_at=None,
    )

    data = _pos_to_dict(cast(Any, position))

    assert data["execution_path"] == "AUTONOMOUS"
    assert data["closing_source"] == "AUTONOMOUS"
    assert data["exemption_detail"] == "manual override"
