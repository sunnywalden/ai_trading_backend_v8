from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd
import pytest

from app.main import (
    _log_factor_snapshot_warmup_result,
    _log_regime_bootstrap_result,
    _log_technical_warmup_result,
    _warm_up_regime_cache,
)
from app.services.regime_classifier import RegimeClassifier


@pytest.mark.asyncio
async def test_score_trend_strict_mode_logs_missing_input(monkeypatch, caplog):
    import yfinance as yf

    monkeypatch.setattr(
        "app.services.regime_classifier.settings.RUNTIME_ALLOW_DECISION_DEFAULTS",
        False,
    )
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: pd.DataFrame())

    with caplog.at_level(logging.WARNING):
        score = await RegimeClassifier()._score_trend()

    assert score is None
    assert "strict real-input mode returns missing input" in caplog.text
    assert "using 50" not in caplog.text


def test_log_regime_bootstrap_result_skipped(caplog):
    with caplog.at_level(logging.WARNING):
        _log_regime_bootstrap_result(
            {
                "skipped": True,
                "reason": "REAL_REGIME_INPUTS_UNAVAILABLE",
                "error": "missing real regime inputs: trend, vol",
            }
        )

    assert "regime bootstrap skipped" in caplog.text
    assert "REAL_REGIME_INPUTS_UNAVAILABLE" in caplog.text
    assert "Market regime refreshed" not in caplog.text


def test_log_technical_warmup_result_deferred(caplog):
    with caplog.at_level(logging.WARNING):
        _log_technical_warmup_result(
            {
                "success": True,
                "success_count": 0,
                "failure_count": 1,
                "symbols_attempted": ["SPY"],
            }
        )

    assert "technical indicator warm-up deferred" in caplog.text
    assert "SPY" in caplog.text
    assert "Technical indicators seeded" not in caplog.text


def test_log_factor_snapshot_warmup_result_deferred(caplog):
    with caplog.at_level(logging.WARNING):
        _log_factor_snapshot_warmup_result({"success": True, "seeded_accounts": 0})

    assert "factor snapshot warm-up deferred" in caplog.text
    assert "Factor exposure snapshot seeded" not in caplog.text


@pytest.mark.asyncio
async def test_warm_up_regime_cache_defers_when_real_inputs_not_ready(monkeypatch, caplog):
    class _FakeSessionContext:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    # 兼容 Python/pytest 环境：显式导入 AsyncMock
    from unittest.mock import AsyncMock

    fake_classifier = SimpleNamespace()
    fake_classifier.get_current_regime = AsyncMock(return_value=None)
    fake_classifier.probe_real_inputs_ready = AsyncMock(
        return_value={"ready": False, "missing": ["breadth", "trend"]}
    )
    fake_classifier.run = AsyncMock()

    monkeypatch.setattr("app.main.SessionLocal", lambda: _FakeSessionContext())
    monkeypatch.setattr("app.main.settings.REGIME_ENABLED", True)
    monkeypatch.setattr("app.main.settings.RUNTIME_ALLOW_DECISION_DEFAULTS", False)
    monkeypatch.setattr(
        "app.services.regime_classifier.regime_classifier",
        fake_classifier,
    )

    with caplog.at_level(logging.WARNING):
        await _warm_up_regime_cache()

    assert "regime bootstrap deferred" in caplog.text
    assert "breadth, trend" in caplog.text
    fake_classifier.run.assert_not_awaited()
