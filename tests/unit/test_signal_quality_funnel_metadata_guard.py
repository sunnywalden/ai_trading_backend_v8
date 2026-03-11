from app.models.signal_quality_audit_log import RejectionReason
from app.services.signal_quality_funnel import SignalFunnelInput, SignalQualityFunnel


def test_layer3_flags_missing_resonance_metadata_explicitly():
    funnel = SignalQualityFunnel()
    signal = SignalFunnelInput(
        signal_id=101,
        symbol="AAPL",
        signal_type="ENTRY",
        direction="LONG",
        regime="BULL_TREND",
        composite_score=0.96,
    )

    reject = funnel._layer3_resonance(
        signal,
        {
            "SIGNAL_RESONANCE_MIN_DIMS": 4,
            "RESONANCE_REQUIRED_TECHNICAL": True,
        },
    )

    assert reject is not None
    assert reject[0] == RejectionReason.MISSING_RESONANCE_METADATA
    assert "缺少共振元数据" in reject[1]


def test_layer3_keeps_real_insufficient_resonance_as_business_reason():
    funnel = SignalQualityFunnel()
    signal = SignalFunnelInput(
        signal_id=102,
        symbol="MSFT",
        signal_type="ENTRY",
        direction="LONG",
        regime="BULL_TREND",
        composite_score=0.97,
        aligned_count=2,
        aligned_dims=["technical", "macro"],
        opposing_dims=["options"],
        neutral_dims=[],
        tech_direction=1,
        fundamental_direction=1,
    )

    reject = funnel._layer3_resonance(
        signal,
        {
            "SIGNAL_RESONANCE_MIN_DIMS": 4,
            "RESONANCE_REQUIRED_TECHNICAL": True,
        },
    )

    assert reject is not None
    assert reject[0] == RejectionReason.INSUFFICIENT_RESONANCE
    assert "同向维度数 2 < 最低要求 4" in reject[1]
