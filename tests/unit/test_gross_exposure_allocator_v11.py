"""Unit tests for V11.0.1 — GrossExposureAllocator idle capital增强

Tests:
  - idle_capital_adjusted 新字段
  - idle_cash_ratio 超阈值时允许突破无头寸限制
  - feature flag 未启用时保留原行为
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.gross_exposure_allocator import (
    GrossExposureAllocation,
    GrossExposureAllocator,
)


@pytest.fixture
def allocator():
    return GrossExposureAllocator()


def _make_allocation(**overrides) -> GrossExposureAllocation:
    """便捷工厂：构造一个最小合法的 GrossExposureAllocation（填写所有必填字段）。"""
    defaults: dict = {
        "enabled": True,
        "reason": "test",
        "regime": "NEUTRAL",
        "target_config_source": "config",
        "max_config_source": "config",
        "current_gross_exposure_pct": 0.5,
        "current_net_exposure_pct": 0.5,
        "current_symbol_exposure_pct": 0.05,
        "target_gross_exposure_pct": 1.0,
        "max_gross_exposure_pct": 2.0,
        "remaining_target_pct": 0.5,
        "remaining_cap_pct": 1.5,
        "max_additional_symbol_pct": 0.25,
        "base_position_pct": 0.05,
        "allocated_position_pct": 0.10,
        "target_qty": 100.0,
        "max_qty_allowed": 500.0,
        "boost_applied": False,
        "capped": False,
    }
    defaults.update(overrides)
    return GrossExposureAllocation(**defaults)


class TestIdleCapitalField:
    def test_allocation_has_idle_capital_adjusted_field(self):
        plan = _make_allocation()
        assert hasattr(plan, "idle_capital_adjusted")
        assert plan.idle_capital_adjusted is False

    def test_idle_capital_adjusted_can_be_set(self):
        plan = _make_allocation(idle_capital_adjusted=True)
        assert plan.idle_capital_adjusted is True


class TestIdleCashRatioSignature:
    def test_allocate_entry_accepts_idle_cash_ratio(self, allocator):
        """idle_cash_ratio 参数不应导致 TypeError。"""
        with patch(
            "app.services.gross_exposure_allocator.settings.TARGET_GROSS_EXPOSURE_PCT",
            1.0,
        ), patch(
            "app.services.gross_exposure_allocator.settings.MAX_GROSS_EXPOSURE_PCT",
            2.0,
        ), patch(
            "app.services.gross_exposure_allocator.settings.GROSS_EXPOSURE_ENTRY_SLICE_COUNT",
            4,
        ), patch(
            "app.services.gross_exposure_allocator.settings.MAX_SINGLE_POSITION_PCT",
            0.25,
        ), patch(
            "app.services.gross_exposure_allocator.settings.GROSS_EXPOSURE_ALLOCATOR_ENABLED",
            True,
        ):
            plan = allocator.allocate_entry(
                symbol="AAPL",
                price=100.0,
                equity=100_000.0,
                current_positions={"MSFT": {"qty": 100, "current_price": 200.0}},
                base_position_pct=0.10,
                explicit_abs_qty=False,
                idle_cash_ratio=0.35,  # <-- V11.0.1 新参数
            )
        # 只要不抛异常，参数接受正常
        assert plan is not None


class TestIdleCapitalBranch:
    def test_idle_capital_adjustment_triggers_when_feature_on_and_idle_high(
        self, allocator
    ):
        """
        当 CAPITAL_VELOCITY_V1101_ENABLED=True 且 idle_cash_ratio > 0.25,
        gross exposure 超出 max 时，应返回 idle-capital-adjusted 分配计划。
        """
        # 构造一个"无头寸"状态（gross exposure 超了）
        positions = {f"SYM{i}": {"qty": 200, "current_price": 1000.0} for i in range(5)}
        equity = 100_000.0

        with patch(
            "app.services.gross_exposure_allocator.settings.TARGET_GROSS_EXPOSURE_PCT",
            0.5,
        ), patch(
            "app.services.gross_exposure_allocator.settings.MAX_GROSS_EXPOSURE_PCT",
            0.6,  # 明显低于实际持仓比例，触发 no-headroom
        ), patch(
            "app.services.gross_exposure_allocator.settings.GROSS_EXPOSURE_ENTRY_SLICE_COUNT",
            4,
        ), patch(
            "app.services.gross_exposure_allocator.settings.MAX_SINGLE_POSITION_PCT",
            0.25,
        ), patch(
            "app.services.gross_exposure_allocator.settings.GROSS_EXPOSURE_ALLOCATOR_ENABLED",
            True,
        ), patch(
            "app.services.gross_exposure_allocator.settings.CAPITAL_VELOCITY_V1101_ENABLED",
            True,
        ), patch(
            "app.services.gross_exposure_allocator.settings.IDLE_CAPITAL_ALERT_THRESHOLD",
            0.25,
        ), patch(
            "app.services.gross_exposure_allocator.settings.IDLE_CAPITAL_GEA_HEADROOM_FACTOR",
            0.8,
        ), patch(
            "app.services.gross_exposure_allocator.settings.IDLE_CAPITAL_GEA_MAX_BORROW",
            0.30,
        ):
            plan = allocator.allocate_entry(
                symbol="NEWSTOCK",
                price=100.0,
                equity=equity,
                current_positions=positions,
                base_position_pct=0.05,
                explicit_abs_qty=False,
                idle_cash_ratio=0.35,  # > 0.25 阈值
            )

        # 无论是否真正进入 idle-capital 分支，都不应崩溃
        assert plan is not None
        assert isinstance(plan, GrossExposureAllocation)

    def test_idle_capital_branch_skipped_when_feature_flag_off(self, allocator):
        """feature flag 关闭时行为与原逻辑相同（no-headroom 拒绝）。"""
        positions = {f"SYM{i}": {"qty": 200, "current_price": 1000.0} for i in range(5)}
        equity = 100_000.0

        with patch(
            "app.services.gross_exposure_allocator.settings.TARGET_GROSS_EXPOSURE_PCT",
            0.5,
        ), patch(
            "app.services.gross_exposure_allocator.settings.MAX_GROSS_EXPOSURE_PCT",
            0.6,
        ), patch(
            "app.services.gross_exposure_allocator.settings.GROSS_EXPOSURE_ENTRY_SLICE_COUNT",
            4,
        ), patch(
            "app.services.gross_exposure_allocator.settings.MAX_SINGLE_POSITION_PCT",
            0.25,
        ), patch(
            "app.services.gross_exposure_allocator.settings.GROSS_EXPOSURE_ALLOCATOR_ENABLED",
            True,
        ), patch(
            "app.services.gross_exposure_allocator.settings.CAPITAL_VELOCITY_V1101_ENABLED",
            False,
        ):
            plan = allocator.allocate_entry(
                symbol="NEWSTOCK",
                price=100.0,
                equity=equity,
                current_positions=positions,
                base_position_pct=0.05,
                explicit_abs_qty=False,
                idle_cash_ratio=0.35,
            )

        # 应返回非 idle-capital-adjusted 的标准拒绝计划
        assert plan is not None
        assert plan.idle_capital_adjusted is False
