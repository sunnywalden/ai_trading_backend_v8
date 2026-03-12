from unittest.mock import patch

import pytest

from app.services.gross_exposure_allocator import GrossExposureAllocator


def test_allocator_boosts_entry_when_gross_exposure_below_target():
    allocator = GrossExposureAllocator()
    positions = {
        "MSFT": {"qty": 100, "current_price": 200.0},
    }

    with patch(
        "app.services.gross_exposure_allocator.settings.TARGET_GROSS_EXPOSURE_PCT",
        1.5,
    ), patch(
        "app.services.gross_exposure_allocator.settings.MAX_GROSS_EXPOSURE_PCT",
        2.0,
    ), patch(
        "app.services.gross_exposure_allocator.settings.GROSS_EXPOSURE_ENTRY_SLICE_COUNT",
        4,
    ), patch(
        "app.services.gross_exposure_allocator.settings.MAX_SINGLE_POSITION_PCT",
        0.25,
    ):
        plan = allocator.allocate_entry(
            symbol="AAPL",
            price=100.0,
            equity=100000.0,
            current_positions=positions,
            base_position_pct=0.10,
            explicit_abs_qty=False,
        )

    assert plan.enabled is True
    assert plan.boost_applied is True
    assert plan.allocated_position_pct == pytest.approx(0.25)
    assert plan.target_qty == pytest.approx(250.0)


def test_allocator_caps_when_symbol_limit_almost_reached():
    allocator = GrossExposureAllocator()
    positions = {
        "AAPL": {"qty": 220, "current_price": 100.0},
    }

    with patch(
        "app.services.gross_exposure_allocator.settings.MAX_SINGLE_POSITION_PCT",
        0.25,
    ), patch(
        "app.services.gross_exposure_allocator.settings.TARGET_GROSS_EXPOSURE_PCT",
        1.5,
    ), patch(
        "app.services.gross_exposure_allocator.settings.MAX_GROSS_EXPOSURE_PCT",
        2.0,
    ):
        plan = allocator.allocate_entry(
            symbol="AAPL",
            price=100.0,
            equity=100000.0,
            current_positions=positions,
            base_position_pct=0.10,
            explicit_abs_qty=False,
        )

    assert plan.capped is True
    assert plan.max_additional_symbol_pct == pytest.approx(0.03)
    assert plan.allocated_position_pct == pytest.approx(0.03)
    assert plan.target_qty == pytest.approx(30.0)


def test_allocator_does_not_boost_explicit_abs_shares_signal():
    allocator = GrossExposureAllocator()
    positions = {}

    with patch(
        "app.services.gross_exposure_allocator.settings.TARGET_GROSS_EXPOSURE_PCT",
        1.5,
    ), patch(
        "app.services.gross_exposure_allocator.settings.MAX_GROSS_EXPOSURE_PCT",
        2.0,
    ), patch(
        "app.services.gross_exposure_allocator.settings.MAX_SINGLE_POSITION_PCT",
        0.25,
    ):
        plan = allocator.allocate_entry(
            symbol="NVDA",
            price=100.0,
            equity=100000.0,
            current_positions=positions,
            base_position_pct=0.05,
            explicit_abs_qty=True,
        )

    assert plan.boost_applied is False
    assert plan.reason == "explicit-abs-shares"
    assert plan.allocated_position_pct == pytest.approx(0.05)
    assert plan.target_qty == pytest.approx(50.0)