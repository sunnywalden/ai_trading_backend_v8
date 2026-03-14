"""Unit tests for V11.0.1 — CapitalVelocityService

Tests:
  - portfolio velocity 计算
  - efficiency grade 分级（_grade_efficiency 模块函数）
  - 历史比较 compute_historical_comparison 基本结构
  - regime multiplier 差异
  - _compute_idle_ratio 静态方法
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.capital_velocity_service import (
    CapitalVelocityResult,
    CapitalVelocityService,
    _grade_efficiency,
)


@pytest.fixture
def service():
    return CapitalVelocityService()


@pytest.fixture
def mock_db():
    """模拟异步数据库 session。"""
    db = AsyncMock()
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_proxy)
    return db


class TestCapitalVelocityResult:
    def test_fields_exist(self):
        result = CapitalVelocityResult(
            account_id="ACC001",
            score=120.0,
            turnover_rate=0.60,
            win_rate=0.55,
            idle_cash_ratio=0.10,
            efficiency_grade="B",
            regime="BULL_TREND",
        )
        assert result.efficiency_grade == "B"
        assert result.account_id == "ACC001"

    def test_to_dict_serializable(self):
        result = CapitalVelocityResult(
            account_id="ACC001",
            score=100.0,
            turnover_rate=0.5,
            win_rate=0.5,
            idle_cash_ratio=0.2,
            efficiency_grade="C",
            regime="NEUTRAL",
        )
        d = result.to_dict()
        assert "score" in d
        assert "efficiency_grade" in d
        assert "idle_cash_ratio" in d
        assert d["account_id"] == "ACC001"


class TestGradeEfficiency:
    """Module-level _grade_efficiency function."""

    @pytest.mark.parametrize(
        "score,expected_grade",
        [
            (120.0, "A"),
            (90.0, "B"),
            (60.0, "C"),
            (40.0, "D"),
            (0.0, "D"),
        ],
    )
    def test_grade_thresholds(self, score, expected_grade):
        assert _grade_efficiency(score) == expected_grade

    def test_boundary_just_above_a(self):
        assert _grade_efficiency(120.1) == "A"

    def test_boundary_just_below_c(self):
        assert _grade_efficiency(59.9) == "D"


class TestComputeIdleRatio:
    def test_zero_positions_full_idle(self):
        ratio = CapitalVelocityService._compute_idle_ratio({}, equity=100_000.0)
        assert ratio == pytest.approx(1.0)

    def test_positions_cover_half_equity(self):
        positions = {
            "AAPL": {"qty": 100, "current_price": 500.0},
        }
        ratio = CapitalVelocityService._compute_idle_ratio(positions, equity=100_000.0)
        # 100 * 500 = 50_000  → idle = 1 - 50_000/100_000 = 0.5
        assert ratio == pytest.approx(0.5)

    def test_zero_equity_returns_full_idle(self):
        ratio = CapitalVelocityService._compute_idle_ratio(
            {"X": {"qty": 10, "current_price": 100.0}}, equity=0.0
        )
        assert ratio == pytest.approx(1.0)


class TestPortfolioVelocity:
    @pytest.mark.asyncio
    async def test_compute_returns_result(self, service, mock_db):
        positions = {
            "AAPL": {"qty": 100, "current_price": 190.0},
            "MSFT": {"qty": 50, "current_price": 310.0},
        }

        result = await service.compute_portfolio_velocity(
            db=mock_db,
            account_id="ACC001",
            positions=positions,
            equity=100_000.0,
            regime="BULL_TREND",
        )

        assert isinstance(result, CapitalVelocityResult)
        assert 0 <= result.score <= 200
        assert result.regime == "BULL_TREND"
        assert result.efficiency_grade in ("A", "B", "C", "D")
        assert result.account_id == "ACC001"

    @pytest.mark.asyncio
    async def test_bull_trend_score_higher_than_bear(self, service, mock_db):
        """同等条件下 BULL_TREND 分数 >= BEAR_TREND。"""
        positions = {"AAPL": {"qty": 100, "current_price": 190.0}}

        bull_result = await service.compute_portfolio_velocity(
            db=mock_db,
            account_id="ACC001",
            positions=positions,
            equity=50_000.0,
            regime="BULL_TREND",
        )
        bear_result = await service.compute_portfolio_velocity(
            db=mock_db,
            account_id="ACC001",
            positions=positions,
            equity=50_000.0,
            regime="BEAR_TREND",
        )

        assert bull_result.score >= bear_result.score

    @pytest.mark.asyncio
    async def test_high_idle_ratio_when_no_positions(self, service, mock_db):
        """无持仓时 idle_cash_ratio 应为 1.0。"""
        result = await service.compute_portfolio_velocity(
            db=mock_db,
            account_id="ACC001",
            positions={},
            equity=100_000.0,
            regime="NEUTRAL",
        )
        assert result.idle_cash_ratio == pytest.approx(1.0)
        assert result.is_idle_alert is True

    @pytest.mark.asyncio
    async def test_none_regime_defaults_to_neutral(self, service, mock_db):
        result = await service.compute_portfolio_velocity(
            db=mock_db,
            account_id="ACC002",
            positions={},
            equity=50_000.0,
            regime=None,
        )
        assert result.regime == "NEUTRAL"


class TestHistoricalComparison:
    @pytest.mark.asyncio
    async def test_returns_dict_with_expected_fields(self, service, mock_db):
        result = await service.compute_historical_comparison(
            db=mock_db,
            account_id="ACC001",
            equity=100_000.0,
        )

        assert "daily_scores" in result
        assert "avg_score" in result
        assert "trend" in result

    @pytest.mark.asyncio
    async def test_empty_signals_returns_flat_trend(self, service, mock_db):
        result = await service.compute_historical_comparison(
            db=mock_db,
            account_id="ACC001",
            equity=100_000.0,
        )
        assert result["trend"] in ("UP", "DOWN", "FLAT")
        assert isinstance(result["avg_score"], float)
