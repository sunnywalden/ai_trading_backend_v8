from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from app.services.paper_trading_service import PaperTradingService


@pytest.mark.asyncio
async def test_check_graduation_includes_governance_gate_when_disabled():
    service = PaperTradingService()
    metrics = {
        "graduation_eligible": True,
        "sharpe": 1.3,
        "max_drawdown": 0.12,
        "win_rate": 0.58,
        "total_trades": 24,
    }

    with patch(
        "app.services.paper_trading_service.backtest_runner.run",
        AsyncMock(return_value=metrics),
    ), patch.object(
        service,
        "get_or_create_account",
        AsyncMock(
            return_value=SimpleNamespace(
                account_id="paper-1",
                positions={"AAPL": {"qty": 1}},
                trade_log=[],
            )
        ),
    ), patch(
        ("app.services.paper_trading_service.settings." "GOVERNANCE_HARD_GATE_ENABLED"),
        False,
    ):
        result = await service.check_graduation(
            account_id="paper-1",
            strategy_name="momentum",
            symbols=["AAPL"],
            db=cast(Any, SimpleNamespace()),
        )

    assert result["eligible"] is True
    assert result["governance_gate"]["gate_applied"] is False
    assert result["governance_gate"]["stage"] == "LIMITED"


@pytest.mark.asyncio
async def test_check_graduation_hard_gate_blocks_insufficient_evidence():
    service = PaperTradingService()
    metrics = {
        "graduation_eligible": True,
        "sharpe": 1.6,
        "max_drawdown": 0.08,
        "win_rate": 0.70,
        "total_trades": 6,
    }

    with patch(
        "app.services.paper_trading_service.backtest_runner.run",
        AsyncMock(return_value=metrics),
    ), patch.object(
        service,
        "get_or_create_account",
        AsyncMock(
            return_value=SimpleNamespace(
                account_id="paper-1",
                positions={"AAPL": {"qty": 1}},
                trade_log=[],
            )
        ),
    ), patch(
        ("app.services.paper_trading_service.settings." "GOVERNANCE_HARD_GATE_ENABLED"),
        True,
    ):
        result = await service.check_graduation(
            account_id="paper-1",
            strategy_name="momentum",
            symbols=["AAPL"],
            db=cast(Any, SimpleNamespace()),
        )

    assert result["eligible"] is False
    assert result["governance_gate"]["gate_applied"] is True
    assert result["governance_gate"]["stage"] == "LIMITED"
    assert (
        "SHADOW_LIVE_EVIDENCE_MISSING"
        in result["governance_gate"]["promotion_blockers"]
    )


@pytest.mark.asyncio
async def test_check_graduation_prefers_real_paper_symbols_and_limits_universe():
    service = PaperTradingService()
    account = SimpleNamespace(
        account_id="paper-1",
        positions={"AMD": {"qty": 10}, "MSFT": {"qty": 5}},
        trade_log=[
            {"symbol": "PLTR"},
            {"symbol": "AMD"},
            {"symbol": "QCOM"},
        ],
    )
    metrics = {
        "graduation_eligible": False,
        "sharpe": 0.8,
        "max_drawdown": 0.11,
        "win_rate": 0.45,
        "total_trades": 12,
    }

    run_mock = AsyncMock(return_value=metrics)
    with patch(
        "app.services.paper_trading_service.backtest_runner.run",
        run_mock,
    ), patch.object(
        service,
        "get_or_create_account",
        AsyncMock(return_value=account),
    ), patch(
        "app.services.paper_trading_service.settings.PAPER_GRADUATION_MAX_SYMBOLS",
        3,
    ):
        result = await service.check_graduation(
            account_id="paper-1",
            strategy_name="momentum",
            symbols=["BRAZ", "AMD", "MSFT", "ORCL", "PLTR", "QCOM"],
            db=cast(Any, SimpleNamespace()),
        )

    assert result["eligible"] is False
    run_mock.assert_awaited_once()
    assert run_mock.await_args.kwargs["symbols"] == ["AMD", "MSFT", "QCOM"]


@pytest.mark.asyncio
async def test_check_graduation_skips_when_no_real_paper_symbols():
    service = PaperTradingService()
    account = SimpleNamespace(
        account_id="paper-1",
        positions={},
        trade_log=[],
    )

    run_mock = AsyncMock()
    with patch(
        "app.services.paper_trading_service.backtest_runner.run",
        run_mock,
    ), patch.object(
        service,
        "get_or_create_account",
        AsyncMock(return_value=account),
    ):
        result = await service.check_graduation(
            account_id="paper-1",
            strategy_name="momentum",
            symbols=["BRAZ", "CAFG", "DSMC"],
            db=cast(Any, SimpleNamespace()),
        )

    assert result["eligible"] is False
    assert "暂不执行毕业评估" in result["message"]
    run_mock.assert_not_awaited()
