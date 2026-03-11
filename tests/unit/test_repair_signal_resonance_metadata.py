from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from scripts.maintenance.repair_signal_resonance_metadata import (
    RESONANCE_REASON_CODE,
    _build_missing_reason_patch,
    _build_repaired_signal_dimensions,
)


def test_build_repaired_signal_dimensions_from_partial_legacy_payload():
    payload = _build_repaired_signal_dimensions(
        {
            "technical_score": 70.0,
            "fundamental_score": 68.0,
            "momentum": 0.76,
            "volume": 0.74,
            "sentiment": 0.79,
            "historical_ic": 0.63,
            "timing_quality": 0.71,
        }
    )

    assert payload is not None
    assert payload["aligned_count"] >= 4
    assert "technical" in payload["aligned_dims"]
    assert len(payload["dimensions"]) == 6
    assert payload["historical_ic"] == 0.63
    assert payload["timing_quality"] == 0.71


def test_build_missing_reason_patch_marks_quality_funnel_rejects():
    signal = SimpleNamespace(
        status=SimpleNamespace(value="REJECTED"),
        risk_check_passed="YES",
        extra_metadata={"watchtower_reason_code": "INSUFFICIENT_RESONANCE"},
    )

    patch = _build_missing_reason_patch(cast(Any, signal))

    assert patch is not None
    assert patch["watchtower_stage"] == "QUALITY_FUNNEL"
    assert patch["watchtower_reason_code"] == RESONANCE_REASON_CODE
    assert patch["watchtower_rejected_at_layer"] == 3
