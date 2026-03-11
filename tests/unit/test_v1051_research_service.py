from types import SimpleNamespace

import pytest

from app.services.v1051_research_service import V1051ResearchService


def test_compute_strategy_stage_thresholds():
    compute_stage = getattr(V1051ResearchService, "_compute_strategy_stage")

    assert compute_stage(True, "SUCCESS", 0.61, 24) == "PRODUCTION"
    assert compute_stage(False, "SUCCESS", 0.58, 12) == "CHALLENGER"
    assert compute_stage(False, "FAILED", 0.0, 4) == "PAPER"
    assert compute_stage(False, None, 0.0, 0) == "DISCOVERY"


def test_summarize_weight_shift_builds_turnover_and_risk_budget():
    summarize_weight_shift = getattr(
        V1051ResearchService,
        "_summarize_weight_shift",
    )
    summary = summarize_weight_shift(
        {"AAPL": 0.2, "MSFT": 0.3, "NVDA": 0.0},
        {"AAPL": 0.1, "MSFT": 0.2, "NVDA": 0.4},
    )

    assert summary["turnover"] == pytest.approx(0.3)
    assert summary["top_weights"][0]["symbol"] == "NVDA"
    assert summary["largest_rebalances"][0]["symbol"] == "NVDA"
    assert sum(item["budget"] for item in summary["risk_budget"]) == pytest.approx(1.0)


def test_summarize_execution_logs_tracks_worst_symbols():
    logs = [
        SimpleNamespace(
            symbol="AAPL",
            total_is_bps=12.0,
            fill_rate=0.8,
            time_to_fill_ms=100,
            quality_score=72,
        ),
        SimpleNamespace(
            symbol="AAPL",
            total_is_bps=18.0,
            fill_rate=0.9,
            time_to_fill_ms=150,
            quality_score=68,
        ),
        SimpleNamespace(
            symbol="TSLA",
            total_is_bps=30.0,
            fill_rate=0.5,
            time_to_fill_ms=240,
            quality_score=51,
        ),
    ]

    summarize_execution_logs = getattr(
        V1051ResearchService,
        "_summarize_execution_logs",
    )
    summary = summarize_execution_logs(logs)

    assert summary["sample_size"] == 3
    assert summary["worst_symbols"][0]["symbol"] == "TSLA"
    assert summary["avg_total_is_bps"] == pytest.approx(20.0)


def test_summarize_signal_bucket_returns_truth_layers_and_quality():
    from datetime import datetime

    signals = [
        SimpleNamespace(
            status="EXECUTED",
            is_winner="YES",
            actual_return=0.06,
            pnl=100,
            pnl_pct=0.052,
            expected_return=0.08,
            confidence=0.9,
            execution_slippage=0.001,
            generated_at=datetime.now(),
            signal_origin_mode="REAL",
            extra_metadata={
                "market_regime": "BULL_TREND",
                "adv_usd": 12_000_000,
                "signal_payload": {"version": "v10.5.4", "origin_mode": "REAL"},
                "signal_transitions": [{"to_status": "EXECUTED"}],
            },
        ),
        SimpleNamespace(
            status="EXECUTED",
            is_winner="NO",
            actual_return=-0.02,
            pnl=-40,
            pnl_pct=-0.023,
            expected_return=0.01,
            confidence=0.7,
            execution_slippage=0.002,
            generated_at=datetime.now(),
            signal_origin_mode="SYNTHETIC",
            extra_metadata={
                "market_regime": "BULL_TREND",
                "adv_usd": 800_000,
                "signal_payload": {
                    "version": "v10.5.4",
                    "origin_mode": "SYNTHETIC",
                },
                "signal_transitions": [{"to_status": "EXECUTED"}],
            },
        ),
    ]

    summarize_signal_bucket = getattr(
        V1051ResearchService,
        "_summarize_signal_bucket",
    )
    summary = summarize_signal_bucket(signals)

    assert summary["gross_return"] == pytest.approx(0.045)
    assert summary["net_return"] == pytest.approx(0.02)
    assert summary["after_cost_return"] == pytest.approx(0.0185)
    assert summary["after_turnover_return"] == pytest.approx(0.0145)
    assert summary["data_quality"] == "INSUFFICIENT"
    assert summary["origin_breakdown"][0]["mode"] == "REAL"
    assert summary["regime_breakdown"][0]["bucket"] == "BULL_TREND"
    assert summary["capacity_breakdown"][0]["bucket"] in {"L", "S"}


def test_build_signal_integrity_summary_tracks_payload_and_transitions():
    signals = [
        SimpleNamespace(
            signal_origin_mode="REAL",
            extra_metadata={
                "signal_payload": {"version": "v10.5.4", "origin_mode": "REAL"},
                "signal_transitions": [{"to_status": "VALIDATED"}],
            },
            factor_scores={},
        ),
        SimpleNamespace(
            signal_origin_mode=None,
            extra_metadata={
                "signal_origin_mode": "BACKFILL",
                "signal_payload": {"version": "legacy", "origin_mode": "BACKFILL"},
            },
            factor_scores={},
        ),
    ]

    build_signal_integrity_summary = getattr(
        V1051ResearchService,
        "_build_signal_integrity_summary",
    )
    summary = build_signal_integrity_summary(signals)

    assert summary["sample_size"] == 2
    assert summary["canonical_payload_ready"] == 1
    assert summary["native_transition_ready"] == 1
    assert summary["origin_known"] == 2


def test_build_rollout_state_promotes_to_semi_when_v1054_control_plane_on(monkeypatch):
    monkeypatch.setattr(
        "app.services.v1051_research_service.settings.SIGNAL_PIPELINE_V1054_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "app.services.v1051_research_service.settings.AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "app.services.v1051_research_service.settings.NATIVE_AUDIT_V1054_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "app.services.v1051_research_service.settings.GOVERNANCE_HARD_GATE_ENABLED",
        False,
    )

    build_rollout_state = getattr(
        V1051ResearchService,
        "_build_rollout_state",
    )
    rollout = build_rollout_state()

    assert rollout["stage"] == "SEMI"
    assert rollout["flags"]["signal_pipeline_v1054_enabled"] is True


def test_summarize_shadow_book_exposes_false_reject_and_protection_benefit():
    ghost_trades = [
        SimpleNamespace(
            ghost_result="WIN",
            ghost_pnl_pct=0.05,
            rejection_reason="QUALITY",
        ),
        SimpleNamespace(
            ghost_result="LOSS",
            ghost_pnl_pct=-0.04,
            rejection_reason="QUALITY",
        ),
        SimpleNamespace(
            ghost_result="LOSS",
            ghost_pnl_pct=-0.02,
            rejection_reason="RISK",
        ),
        SimpleNamespace(
            ghost_result="OPEN",
            ghost_pnl_pct=None,
            rejection_reason="RISK",
        ),
    ]

    summarize_shadow_book = getattr(
        V1051ResearchService,
        "_summarize_shadow_book",
    )
    summary = summarize_shadow_book(ghost_trades)

    assert summary["closed"] == 3
    assert summary["false_reject_rate"] == pytest.approx(0.3333)
    assert summary["missed_alpha_pct"] == pytest.approx(0.05)
    assert summary["avoided_loss_pct"] == pytest.approx(0.03)
    assert summary["protection_benefit_pct"] == pytest.approx(-0.02)


def test_compute_governance_stage_supports_five_stage_pipeline():
    compute_governance_stage = getattr(
        V1051ResearchService,
        "_compute_governance_stage",
    )

    assert compute_governance_stage(False, None, 0.0, 0) == "DISCOVERY"
    assert compute_governance_stage(False, "FAILED", 0.4, 3) == "PAPER"
    assert compute_governance_stage(False, "SUCCESS", 0.52, 12) == "SHADOW_LIVE"
    assert compute_governance_stage(False, "SUCCESS", 0.56, 24) == "CHALLENGER"
    assert compute_governance_stage(True, "SUCCESS", 0.60, 36) == "PRODUCTION"
