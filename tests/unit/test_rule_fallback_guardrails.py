from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.services.ai_advice_service import AiAdviceService
from app.services.ai_analysis_service import AIAnalysisService
from app.schemas.ai_advice import AiAdviceRequest, RiskPreference


@pytest.mark.asyncio
async def test_ai_analysis_position_advice_does_not_use_rule_fallback_when_disabled(monkeypatch):
    monkeypatch.setattr("app.services.ai_analysis_service.settings.RUNTIME_ALLOW_RULE_BASED_FALLBACK", False)

    service = AIAnalysisService()
    service._call_gpt = AsyncMock(return_value=None)

    advice = await service.generate_position_advice(
        symbol="AAPL",
        position_data={"current_price": 100, "avg_cost": 90, "return_pct": 5, "quantity": 10},
        technical_score=70,
        fundamental_score=75,
        overall_score=72,
    )

    assert "已禁用规则回退" in advice


@pytest.mark.asyncio
async def test_ai_advice_no_placeholder_orders_when_ai_key_missing(monkeypatch):
    monkeypatch.setattr("app.services.ai_advice_service.settings.OPENAI_API_KEY", None)

    service = AiAdviceService(session=cast(Any, SimpleNamespace()))
    service.build_state_snapshot = AsyncMock(
        return_value=SimpleNamespace(
            trade_mode="REAL",
            limits=SimpleNamespace(model_dump=lambda: {}),
            exposure=SimpleNamespace(model_dump=lambda: {}),
            symbols={},
        )
    )
    response = await service.get_advice(
        AiAdviceRequest(
            account_id="acc-1",
            goal="稳健增值",
            time_horizon="SWING",
            risk_preference=RiskPreference(level="MEDIUM", max_drawdown_pct=0.2, target_vol_pct=0.25),
            notes="",
        )
    )

    assert response.suggested_orders == []
    assert "示例" not in response.summary


@pytest.mark.asyncio
async def test_kline_analysis_returns_unavailable_when_rule_fallback_disabled(monkeypatch):
    monkeypatch.setattr("app.services.ai_advice_service.settings.RUNTIME_ALLOW_RULE_BASED_FALLBACK", False)
    monkeypatch.setattr(
        "app.services.ai_advice_service.BarPeriod",
        SimpleNamespace(WEEK="WEEK", DAY="DAY", FOUR_HOURS="FOUR_HOURS", TWO_HOURS="TWO_HOURS", ONE_HOUR="ONE_HOUR"),
    )

    service = AiAdviceService(session=cast(Any, SimpleNamespace()))
    service.market_provider = cast(Any, SimpleNamespace(_get_tiger_bars=AsyncMock(return_value=[])))
    monkeypatch.setattr(
        "app.services.ai_advice_service.call_ai_with_fallback",
        AsyncMock(return_value=(None, None)),
    )

    response = await service.analyze_stock_kline("AAPL")

    assert response.action == "HOLD"
    assert "规则回退已禁用" in response.suggestion
