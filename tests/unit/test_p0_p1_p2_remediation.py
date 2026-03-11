"""P0 / P1 / P2 信号管道整改验收测试

覆盖所有本轮整改项目：
  P0.1 — signal_origin_mode 标签（SYNTHETIC / REAL）
  P0.2 — 更新已有信号时重置 watchtower 状态
  P0.3 — /execute-signals 已发出 DEPRECATED 警告（静态验证）
  P1.1 — validate_signal 记录状态流转历史 (status_history)
  P1.3 — RiskGateService.sync_regime_from_db 运作正确
  P2   — _fallback_signal_to_dict 使用 result_source="RECONSTRUCTED"
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engine.signal_engine import SignalEngine
from app.jobs.strategy_jobs import _sample_assets
from app.services.risk_gate_service import RiskGateService
from app.services.signal_audit_log_service import SignalAuditLogService
from app.services.signal_transition_service import signal_transition_service


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

class _FakeExecResult:
    def __init__(self, item):
        self._item = item

    def scalars(self):
        return self

    def first(self):
        return self._item


# ───────────────────────────────────────────────────────────────────────────
# P0.1 — signal_origin_mode 标签
# ───────────────────────────────────────────────────────────────────────────

def test_sample_assets_tags_synthetic_origin():
    """P0.1: strategy_jobs._sample_assets() 输出的 signal_dimensions 应标记 SYNTHETIC。"""
    assets = _sample_assets(
        count=5,
        strategy_name="量化策略",
        universe_symbols=["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"],
    )
    for asset in assets:
        dims = asset["signal_dimensions"]
        assert dims.get("signal_origin_mode") == "SYNTHETIC", (
            f"Expected signal_origin_mode='SYNTHETIC', got {dims.get('signal_origin_mode')!r}"
        )


@pytest.mark.asyncio
async def test_new_signal_gets_real_origin_mode_by_default():
    """P0.1: 当 signal_dims 不含 signal_origin_mode 时，新建信号应默认为 'REAL'。"""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeExecResult(None))
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    engine = object.__new__(SignalEngine)
    engine.session = session
    engine.risk_svc = cast(Any, None)
    engine.account_svc = cast(Any, None)
    engine.broker = cast(Any, None)

    # Build an asset WITHOUT signal_origin_mode in signal_dimensions
    asset_dims: dict = {
        "aligned_count": 5,
        "aligned_dims": ["technical", "fundamental", "macro", "options", "flow"],
        "opposing_dims": [],
        "neutral_dims": ["sentiment"],
        "dimensions": [
            {"name": d, "direction": 1, "score": 80.0}
            for d in ["technical", "fundamental", "macro", "options", "flow", "sentiment"]
        ],
        "macro_score": 80.0,
        "options_score": 78.0,
        "adv_usd": 5_000_000,
        "market_cap": 2_000_000_000,
        "historical_ic": 0.06,
        "timing_quality": 0.75,
    }

    strategy_run = SimpleNamespace(
        account_id="acc-1",
        strategy_id="strat-1",
        id="run-1",
        direction="LONG",
        user_id="user-1",
        strategy_version="v1",
        target_universe="US_ALL_LOCAL",
        strategy=SimpleNamespace(name="RealStrategy"),
    )
    asset = SimpleNamespace(
        symbol="TSLA",
        signal_strength=85.0,
        signal_dimensions=asset_dims,
    )

    with patch.object(SignalEngine, "_infer_signal_type", new=AsyncMock(return_value="ENTRY")):
        result = await SignalEngine._create_signal_from_asset(engine, cast(Any, strategy_run), cast(Any, asset))

    # _create_signal_from_asset calls session.add() with a TradingSignal; capture it
    assert session.add.called
    created_signal = session.add.call_args[0][0]
    assert created_signal.signal_origin_mode == "REAL", (
        f"Expected 'REAL', got {created_signal.signal_origin_mode!r}"
    )
    payload = created_signal.extra_metadata.get("signal_payload")
    assert isinstance(payload, dict)
    assert payload["version"] == "v10.5.4"
    assert payload["origin_mode"] == "REAL"
    assert payload["execution_hints"]["direction"] == "LONG"


@pytest.mark.asyncio
async def test_new_signal_inherits_synthetic_origin_mode():
    """P0.1: 当 signal_dims 含 signal_origin_mode='SYNTHETIC' 时，新建信号应继承该标记。"""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeExecResult(None))
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    engine = object.__new__(SignalEngine)
    engine.session = session
    engine.risk_svc = cast(Any, None)
    engine.account_svc = cast(Any, None)
    engine.broker = cast(Any, None)

    sampled = _sample_assets(count=1, strategy_name="量化策略", universe_symbols=["AAPL"])[0]
    assert sampled["signal_dimensions"]["signal_origin_mode"] == "SYNTHETIC"

    strategy_run = SimpleNamespace(
        account_id="acc-1",
        strategy_id="strat-1",
        id="run-1",
        direction="LONG",
        user_id="user-1",
        strategy_version="v1",
        target_universe="US_ALL_LOCAL",
        strategy=SimpleNamespace(name="SyntheticStrategy"),
    )
    asset = SimpleNamespace(
        symbol=sampled["symbol"],
        signal_strength=sampled["signal_strength"],
        signal_dimensions=sampled["signal_dimensions"],
    )

    with patch.object(SignalEngine, "_infer_signal_type", new=AsyncMock(return_value="ENTRY")):
        await SignalEngine._create_signal_from_asset(engine, cast(Any, strategy_run), cast(Any, asset))

    created_signal = session.add.call_args[0][0]
    assert created_signal.signal_origin_mode == "SYNTHETIC"
    payload = created_signal.extra_metadata.get("signal_payload")
    assert isinstance(payload, dict)
    assert payload["origin_mode"] == "SYNTHETIC"


# ───────────────────────────────────────────────────────────────────────────
# P0.2 — 更新已有信号时重置 watchtower 状态
# ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_signal_update_resets_watchtower_to_pending():
    """P0.2: 当现有信号以更高强度更新时，watchtower_result 和 watchtower_stage 必须重置。"""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    existing_signal = SimpleNamespace(
        signal_strength=60.0,
        confidence=0.6,
        expected_return=0.02,
        risk_score=55.0,
        suggested_quantity=0.1,
        quantity_mode="PCT_EQUITY",
        quantity_value=0.1,
        priority=60,
        strategy_run_id="old-run",
        expired_at=None,
        signal_origin_mode="REAL",
        factor_scores={"technical_score": 55.0},
        # Simulates a previously REJECTED signal
        extra_metadata={
            "watchtower_stage": "SIGNAL_VALIDATION",
            "watchtower_result": "REJECTED",
            "watchtower_reason_code": "LOW_QUALITY",
        },
    )
    session.execute.return_value = _FakeExecResult(existing_signal)

    engine = object.__new__(SignalEngine)
    engine.session = session
    engine.risk_svc = cast(Any, None)
    engine.account_svc = cast(Any, None)
    engine.broker = cast(Any, None)

    sampled = _sample_assets(count=1, strategy_name="量化策略", universe_symbols=["MSFT"])[0]

    strategy_run = SimpleNamespace(
        account_id="acc-1",
        strategy_id="strat-1",
        id="run-new",
        direction="LONG",
        user_id="user-1",
        strategy_version="v2",
        target_universe="US_ALL_LOCAL",
        strategy=SimpleNamespace(name="UpgradedStrategy"),
    )
    asset = SimpleNamespace(
        symbol="MSFT",
        signal_strength=95.0,  # stronger than existing 60.0
        signal_dimensions=sampled["signal_dimensions"],
    )

    result = await SignalEngine._create_signal_from_asset(engine, cast(Any, strategy_run), cast(Any, asset))

    assert result is existing_signal
    assert existing_signal.signal_strength == 95.0
    # P0.2: old REJECTED state must be cleared
    assert existing_signal.extra_metadata["watchtower_result"] == "PENDING", (
        "watchtower_result should be reset to PENDING after signal update"
    )
    assert existing_signal.extra_metadata["watchtower_stage"] == "SIGNAL_GENERATION", (
        "watchtower_stage should be reset to SIGNAL_GENERATION after signal update"
    )
    assert existing_signal.extra_metadata.get("watchtower_reason_code") is None
    assert existing_signal.extra_metadata["signal_payload"]["version"] == "v10.5.4"


@pytest.mark.asyncio
async def test_signal_update_propagates_synthetic_origin():
    """P0.1+P0.2: 更新信号时，如新信号为 SYNTHETIC，则覆盖 origin mode。"""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    existing_signal = SimpleNamespace(
        signal_strength=50.0,
        confidence=0.5,
        expected_return=0.01,
        risk_score=50.0,
        suggested_quantity=0.1,
        quantity_mode="PCT_EQUITY",
        quantity_value=0.1,
        priority=50,
        strategy_run_id="run-0",
        expired_at=None,
        signal_origin_mode="REAL",
        factor_scores={},
        extra_metadata={},
    )
    session.execute.return_value = _FakeExecResult(existing_signal)

    engine = object.__new__(SignalEngine)
    engine.session = session
    engine.risk_svc = cast(Any, None)
    engine.account_svc = cast(Any, None)
    engine.broker = cast(Any, None)

    sampled = _sample_assets(count=1, strategy_name="量化策略", universe_symbols=["NVDA"])[0]
    # sampled has signal_origin_mode=SYNTHETIC in signal_dimensions

    strategy_run = SimpleNamespace(
        account_id="acc-1",
        strategy_id="strat-1",
        id="run-syn",
        direction="LONG",
        user_id="user-1",
        strategy_version="v1",
        target_universe="US_ALL_LOCAL",
        strategy=SimpleNamespace(name="SynStrategy"),
    )
    asset = SimpleNamespace(
        symbol="NVDA",
        signal_strength=99.0,
        signal_dimensions=sampled["signal_dimensions"],
    )

    result = await SignalEngine._create_signal_from_asset(engine, cast(Any, strategy_run), cast(Any, asset))
    assert result is existing_signal
    assert existing_signal.signal_origin_mode == "SYNTHETIC"
    assert existing_signal.extra_metadata["signal_payload"]["origin_mode"] == "SYNTHETIC"


# ───────────────────────────────────────────────────────────────────────────
# P1.1 — _record_transition 辅助方法验证
# ───────────────────────────────────────────────────────────────────────────

def test_record_transition_appends_to_status_history():
    """P1.1: _record_transition 应将流转记录追加到 meta['status_history']。"""
    meta: dict = {}
    SignalEngine._record_transition(meta, from_status="GENERATED", to_status="VALIDATED", reason="ALL_CHECKS_PASSED")
    assert "status_history" in meta
    assert len(meta["status_history"]) == 1
    entry = meta["status_history"][0]
    assert entry["from"] == "GENERATED"
    assert entry["to"] == "VALIDATED"
    assert entry["reason"] == "ALL_CHECKS_PASSED"
    assert "at" in entry
    assert "signal_transitions" in meta
    assert meta["signal_transitions"][0]["actor"] == "SIGNAL_ENGINE"
    assert meta["signal_transitions"][0]["result_source"] == "NATIVE_TRANSITION_LOG"


def test_record_transition_preserves_existing_history():
    """P1.1: _record_transition 应保留已有的历史记录，仅追加新条目。"""
    meta: dict = {"status_history": [{"from": "GENERATED", "to": "QUEUED", "at": "T0", "reason": None}]}
    SignalEngine._record_transition(meta, from_status="QUEUED", to_status="EXECUTING")
    assert len(meta["status_history"]) == 2
    assert meta["status_history"][-1]["from"] == "QUEUED"


def test_record_transition_caps_history_at_20():
    """P1.1: status_history 最多保留最近 20 条，防止 JSON 膨胀。"""
    meta: dict = {
        "status_history": [
            {"from": "A", "to": "B", "at": f"T{i}", "reason": None} for i in range(22)
        ]
    }
    SignalEngine._record_transition(meta, from_status="X", to_status="Y")
    assert len(meta["status_history"]) == 20


def test_record_transition_handles_corrupt_history():
    """P1.1: 若 status_history 不是 list，应重置为 list 后追加。"""
    meta: dict = {"status_history": "corrupted_string"}
    SignalEngine._record_transition(meta, from_status="GENERATED", to_status="EXPIRED")
    assert isinstance(meta["status_history"], list)
    assert meta["status_history"][-1]["to"] == "EXPIRED"


def test_signal_transition_service_latest_transition_reads_native_log():
    meta = signal_transition_service.append_transition(
        {},
        from_status="VALIDATED",
        to_status="QUEUED",
        actor="AUTONOMOUS_ENGINE",
        stage="CONTROL_PLANE",
        reason_code="STATUS_QUEUED",
        correlation_id="cycle-001",
    )

    latest = signal_transition_service.latest_transition(meta)

    assert latest is not None
    assert latest["from_status"] == "VALIDATED"
    assert latest["to_status"] == "QUEUED"
    assert latest["actor"] == "AUTONOMOUS_ENGINE"
    assert latest["correlation_id"] == "cycle-001"


# ───────────────────────────────────────────────────────────────────────────
# P1.3 — RiskGateService.sync_regime_from_db
# ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_regime_from_db_updates_multiplier():
    """P1.3: sync_regime_from_db 应读取最新体制并调用 set_regime_var_multiplier。"""
    svc = RiskGateService()
    initial_multiplier = svc.get_regime_var_multiplier()

    fake_regime = SimpleNamespace(regime="BULL_TREND")
    fake_db = MagicMock()

    with patch("app.services.regime_classifier.RegimeClassifier.get_current_regime", new=AsyncMock(return_value=fake_regime)):
        with patch.object(svc, "set_regime_var_multiplier") as mock_set:
            await svc.sync_regime_from_db(fake_db)
            mock_set.assert_called_once_with("BULL_TREND")


@pytest.mark.asyncio
async def test_sync_regime_from_db_no_regime_is_noop():
    """P1.3: 若 DB 中无活跃体制，sync_regime_from_db 不应改变 multiplier。"""
    svc = RiskGateService()
    fake_db = MagicMock()

    with patch("app.services.regime_classifier.RegimeClassifier.get_current_regime", new=AsyncMock(return_value=None)):
        with patch.object(svc, "set_regime_var_multiplier") as mock_set:
            await svc.sync_regime_from_db(fake_db)
            mock_set.assert_not_called()


@pytest.mark.asyncio
async def test_sync_regime_from_db_exception_is_non_fatal():
    """P1.3: sync_regime_from_db 中的异常应被捕获，不应向外传播。"""
    svc = RiskGateService()
    fake_db = MagicMock()

    with patch("app.services.regime_classifier.RegimeClassifier.get_current_regime", new=AsyncMock(side_effect=RuntimeError("DB error"))):
        # Should NOT raise even if DB call fails
        await svc.sync_regime_from_db(fake_db)


# ───────────────────────────────────────────────────────────────────────────
# P2 — _fallback_signal_to_dict result_source
# ───────────────────────────────────────────────────────────────────────────

def test_fallback_audit_uses_reconstructed_source():
    """P2: _fallback_signal_to_dict 应返回 result_source='RECONSTRUCTED'。"""
    svc = SignalAuditLogService()

    fake_signal = SimpleNamespace(
        signal_id="sig-001",
        symbol="AAPL",
        status="GENERATED",
        signal_strength=80.0,
        confidence=0.80,
        signal_type="ENTRY",
        signal_source="STRATEGY",
        direction="LONG",
        account_id="acc-1",
        strategy_id="strat-1",
        strategy_run_id="run-1",
        priority=80,
        created_at=None,
        updated_at=None,
        generated_at=None,
        validated_at=None,
        expired_at=None,
        executed_at=None,
        risk_check_passed=None,
        risk_check_details=None,
        validation_errors=None,
        factor_scores=None,
        notes=None,
        tags=None,
        extra_metadata={
            "watchtower_stage": "SIGNAL_GENERATION",
            "watchtower_result": "PENDING",
            "aligned_count": 4,
            "aligned_dims": ["technical", "fundamental", "macro", "options"],
            "opposing_dims": [],
            "neutral_dims": [],
            "dimensions": [],
        },
    )

    result = svc._fallback_signal_to_dict(fake_signal, regime="BULL_TREND")
    assert result["result_source"] == "RECONSTRUCTED", (
        f"Expected 'RECONSTRUCTED', got {result['result_source']!r}"
    )


def test_fallback_audit_prefers_native_transition_source_when_present():
    svc = SignalAuditLogService()

    fake_signal = SimpleNamespace(
        id=101,
        signal_id="sig-native-001",
        symbol="NVDA",
        status="QUEUED",
        signal_strength=91.0,
        confidence=0.91,
        signal_type="ENTRY",
        signal_source="STRATEGY",
        direction="LONG",
        account_id="acc-1",
        strategy_id="strat-1",
        strategy_run_id="run-1",
        priority=91,
        created_at=None,
        updated_at=None,
        generated_at=None,
        validated_at=None,
        expired_at=None,
        executed_at=None,
        risk_check_passed="YES",
        risk_check_details=None,
        validation_errors=None,
        factor_scores=None,
        notes=None,
        tags=None,
        extra_metadata={
            "signal_transitions": [
                {
                    "from_status": "VALIDATED",
                    "to_status": "QUEUED",
                    "at": "2026-03-11T00:00:00",
                    "actor": "AUTONOMOUS_ENGINE",
                    "stage": "CONTROL_PLANE",
                    "reason_code": "STATUS_QUEUED",
                    "reason_detail": "Signal reserved for autonomous cycle",
                    "correlation_id": "cycle-42",
                    "result_source": "NATIVE_TRANSITION_LOG",
                }
            ]
        },
    )

    result = svc._fallback_signal_to_dict(fake_signal, regime="BULL_TREND")

    assert result["result_source"] == "NATIVE_TRANSITION_LOG"
    assert result["decision_stage"] == "CONTROL_PLANE"
    assert result["rejection_reason"] == "STATUS_QUEUED"


def test_native_audit_log_row_uses_signal_quality_audit_log_source():
    """P2: _row_to_dict (native audit log path) 应保持 result_source='SIGNAL_QUALITY_AUDIT_LOG'。"""
    from app.services.signal_audit_log_service import SignalAuditLogService
    svc = SignalAuditLogService()

    from app.models.signal_quality_audit_log import FunnelResult, SignalQualityAuditLog
    import datetime

    fake_row = SimpleNamespace(
        id=1,
        signal_id="sig-002",
        symbol="MSFT",
        account_id="acc-1",
        strategy_run_id="run-2",
        regime="BEAR_CAUTION",
        funnel_result=FunnelResult.PASSED,
        quality_score=72.0,
        quality_tier="GOOD",
        quota_exempt=False,
        anti_resonance_triggered=False,
        rejected_at_layer=None,
        rejection_layer=None,
        rejection_reason=None,
        rejection_detail=None,
        rejection_reason_detail=None,
        rejection_reason_category=None,
        conviction_score=None,
        composite_score=72.0,
        resonance_bonus=None,
        regime_alignment=None,
        calibrated_lower_bound=None,
        aligned_count=3,
        aligned_dims=["technical", "macro", "options"],
        opposing_dims=[],
        neutral_dims=["fundamental", "flow", "sentiment"],
        signal_direction="LONG",
        tech_direction=1,
        fundamental_direction=None,
        historical_ic=0.05,
        timing_quality=0.70,
        signal_strength=82.0,
        confidence=0.82,
        signal_type="ENTRY",
        signal_source="STRATEGY",
        direction="LONG",
        priority=82,
        concurrent_positions=None,
        daily_signals_used=None,
        generated_at=None,
        evaluated_at=None,
        created_at=datetime.datetime(2024, 1, 1),
        extra_metadata={},
    )

    row_dict = svc._row_to_dict(cast(Any, fake_row))
    assert row_dict["result_source"] == "SIGNAL_QUALITY_AUDIT_LOG"
