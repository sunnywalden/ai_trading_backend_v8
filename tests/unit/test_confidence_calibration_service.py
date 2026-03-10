from __future__ import annotations

from datetime import date, datetime

from app.services.confidence_calibration_service import (
    _build_calibration_buckets,
    _snap_to_dict,
)


class _SnapStub:
    def __init__(self, calibration_buckets):
        self.id = 1
        self.snapshot_date = date(2026, 3, 10)
        self.brier_score = 0.1234
        self.ece = 0.0567
        self.overconfidence_bias = 0.01
        self.calibration_buckets = calibration_buckets
        self.total_samples = 27
        self.valid_bucket_count = 1
        self.needs_adjustment = False
        self.adjustment_factor = None
        self.created_at = datetime(2026, 3, 10, 8, 15, 0)


def test_build_calibration_buckets_includes_numeric_bounds():
    buckets = _build_calibration_buckets([0.05, 0.22, 0.87], [0.0, 1.0, 1.0])

    assert buckets[0]["bucket"] == "0.0-0.1"
    assert buckets[0]["bucket_start"] == 0.0
    assert buckets[0]["bucket_end"] == 0.1
    assert buckets[-1]["bucket"] == "0.9-1.0"
    assert buckets[-1]["bucket_start"] == 0.9
    assert buckets[-1]["bucket_end"] == 1.0


def test_snap_to_dict_normalizes_legacy_bucket_ranges():
    snap = _SnapStub([
        {
            "bucket": "0.4-0.5",
            "count": 3,
            "predicted_rate": 0.45,
            "actual_rate": 0.33,
            "gap": 0.12,
        }
    ])

    payload = _snap_to_dict(snap)

    assert payload["calibration_buckets"] == [
        {
            "bucket": "0.4-0.5",
            "bucket_start": 0.4,
            "bucket_end": 0.5,
            "count": 3,
            "predicted_rate": 0.45,
            "actual_rate": 0.33,
            "gap": 0.12,
        }
    ]