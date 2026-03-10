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
        AsyncMock(return_value=SimpleNamespace(account_id="paper-1")),
    ), patch(
        (
            "app.services.paper_trading_service.settings."
            "GOVERNANCE_HARD_GATE_ENABLED"
        ),
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
    assert result["governance_gate"]["stage"] == "CHALLENGER"


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
        AsyncMock(return_value=SimpleNamespace(account_id="paper-1")),
    ), patch(
        (
            "app.services.paper_trading_service.settings."
            "GOVERNANCE_HARD_GATE_ENABLED"
        ),
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
    assert result["governance_gate"]["stage"] == "PAPER"
    assert (
        "SHADOW_LIVE_EVIDENCE_MISSING"
        in result["governance_gate"]["promotion_blockers"]
    )
