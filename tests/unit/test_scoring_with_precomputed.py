import pytest
import asyncio

from app.services.position_scoring_service import PositionScoringService
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_calculate_position_score_with_precomputed():
    service = PositionScoringService()

    # Precompute a minimal technical DTO-like object
    tech_stub = SimpleNamespace(
        trend_strength=60,
        rsi=SimpleNamespace(value=50, status="NORMAL", signal=None),
        macd=SimpleNamespace(value=0.1, signal_line=0.05, histogram=0.05, status="BULLISH_CROSSOVER"),
        resistance_levels=[120.0],
        volume_ratio=1.0
    )

    # Call scoring with precomputed technical data, no network expected
    score = await service.calculate_position_score("FAKE", current_price=100.0, technical_data=tech_stub)

    assert score is not None
    assert hasattr(score, 'overall_score')
    assert score.overall_score >= 0
