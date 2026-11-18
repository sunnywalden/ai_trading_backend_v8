from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.position_score import PositionScore
from app.services.fundamental_analysis_service import FundamentalAnalysisService
from app.services.position_scoring_service import PositionScoringService


@pytest.mark.asyncio
async def test_calculate_position_score_with_precomputed(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(PositionScore.__table__.create)

    async def _offline_fundamental(self, symbol, force_refresh=False):
        raise RuntimeError("offline fundamental source")

    monkeypatch.setattr(
        FundamentalAnalysisService,
        "get_fundamental_data",
        _offline_fundamental,
    )
    service = PositionScoringService()
    monkeypatch.setattr(service, "_get_session", session_factory)

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
