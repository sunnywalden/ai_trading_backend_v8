from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.trading_signal import SignalStatus
from scripts.diagnostics.diag_signal_origin_pipeline import _normalize_origin
from scripts.maintenance.cleanup_synthetic_pending_signals import (
    _matches_synthetic_pending,
)


def test_normalize_origin_accepts_known_values():
    assert _normalize_origin("real") == "REAL"
    assert _normalize_origin("SYNTHETIC") == "SYNTHETIC"
    assert _normalize_origin(None) == "UNKNOWN"


def test_matches_synthetic_pending_respects_status_and_origin_sources():
    signal = SimpleNamespace(
        status=SignalStatus.GENERATED,
        signal_origin_mode="SYNTHETIC",
        extra_metadata={},
    )
    assert _matches_synthetic_pending(signal, include_queued=False) is True

    queued = SimpleNamespace(
        status=SignalStatus.QUEUED,
        signal_origin_mode=None,
        extra_metadata={"signal_payload": {"origin_mode": "SYNTHETIC"}},
    )
    assert _matches_synthetic_pending(queued, include_queued=False) is False
    assert _matches_synthetic_pending(queued, include_queued=True) is True

    real_signal = SimpleNamespace(
        status=SignalStatus.VALIDATED,
        signal_origin_mode="REAL",
        extra_metadata={},
    )
    assert _matches_synthetic_pending(real_signal, include_queued=True) is False
