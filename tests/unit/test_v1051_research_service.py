from types import SimpleNamespace

from app.services.v1051_research_service import V1051ResearchService


def test_compute_strategy_stage_thresholds():
    assert V1051ResearchService._compute_strategy_stage(True, "SUCCESS", 0.61, 24) == "PRODUCTION"
    assert V1051ResearchService._compute_strategy_stage(False, "SUCCESS", 0.58, 12) == "CHALLENGER"
    assert V1051ResearchService._compute_strategy_stage(False, "FAILED", 0.0, 4) == "PAPER"
    assert V1051ResearchService._compute_strategy_stage(False, None, 0.0, 0) == "DISCOVERY"


def test_summarize_weight_shift_builds_turnover_and_risk_budget():
    summary = V1051ResearchService._summarize_weight_shift(
        {"AAPL": 0.2, "MSFT": 0.3, "NVDA": 0.0},
        {"AAPL": 0.1, "MSFT": 0.2, "NVDA": 0.4},
    )

    assert summary["turnover"] == 0.3
    assert summary["top_weights"][0]["symbol"] == "NVDA"
    assert summary["largest_rebalances"][0]["symbol"] == "NVDA"
    assert round(sum(item["budget"] for item in summary["risk_budget"]), 4) == 1.0


def test_summarize_execution_logs_tracks_worst_symbols():
    logs = [
        SimpleNamespace(symbol="AAPL", total_is_bps=12.0, fill_rate=0.8, time_to_fill_ms=100, quality_score=72),
        SimpleNamespace(symbol="AAPL", total_is_bps=18.0, fill_rate=0.9, time_to_fill_ms=150, quality_score=68),
        SimpleNamespace(symbol="TSLA", total_is_bps=30.0, fill_rate=0.5, time_to_fill_ms=240, quality_score=51),
    ]

    summary = V1051ResearchService._summarize_execution_logs(logs)

    assert summary["sample_size"] == 3
    assert summary["worst_symbols"][0]["symbol"] == "TSLA"
    assert summary["avg_total_is_bps"] == 20.0