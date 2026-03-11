import asyncio
from datetime import datetime
from math import isclose
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.execution_policy_profile import ExecutionPolicyProfile
from app.services.execution_policy_service import ExecutionPolicyService


class _FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None

    def one_or_none(self):
        return self.first()

    def one(self):
        if not self._items:
            raise AssertionError("Expected one item but result was empty")
        return self._items[0]


class _FakeExecuteResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalarResult(self._items)


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)

    async def execute(self, _stmt):
        await asyncio.sleep(0)
        return _FakeExecuteResult(self._responses.pop(0))


def test_derive_policy_snapshot_prefers_closing_market_path():
    intent = SimpleNamespace(
        action="SELL",
        status="SUCCESS",
        qty=120,
        reason=None,
    )
    log = SimpleNamespace(
        algo_type=None,
        fill_rate=1.0,
        quality_score=88.0,
        total_is_bps=9.2,
    )

    derive_policy_snapshot = getattr(
        ExecutionPolicyService,
        "_derive_policy_snapshot",
    )
    policy = derive_policy_snapshot(intent, log)

    assert policy["urgency"] == "FORCED"
    assert policy["algo_type"] == "MARKET"
    assert policy["closing_override_policy"] is True


def test_derive_pretrade_cost_uses_logged_components_when_present():
    intent = SimpleNamespace(qty=300)
    log = SimpleNamespace(
        delay_cost_bps=3.2,
        market_impact_bps=5.4,
        opportunity_cost_bps=2.1,
        timing_cost_bps=1.7,
    )

    derive_pretrade_cost = getattr(
        ExecutionPolicyService,
        "_derive_pretrade_cost",
    )
    pretrade = derive_pretrade_cost(intent, log)

    assert isclose(pretrade["total_expected_cost_bps"], 12.4, rel_tol=1e-9)
    assert isclose(pretrade["market_impact_bps"], 5.4, rel_tol=1e-9)


def test_build_exceptions_flags_slippage_breach_and_fill_rate():
    intent = SimpleNamespace(status="SUCCESS", reason=None)
    log = SimpleNamespace(total_is_bps=26.0, fill_rate=0.52)
    policy = {"slippage_budget_bps": 18.0}

    build_exceptions = getattr(ExecutionPolicyService, "_build_exceptions")
    exceptions = build_exceptions(intent, log, policy)

    kinds = {item["type"] for item in exceptions}
    assert "SLIPPAGE_BUDGET_BREACH" in kinds
    assert "LOW_FILL_RATE" in kinds


def test_hard_control_state_reflects_feature_flag():
    with patch(
        (
            "app.services.execution_policy_service.settings."
            "EXECUTION_POLICY_HARD_CONTROL_ENABLED"
        ),
        True,
    ):
        hard_control_state = getattr(
            ExecutionPolicyService,
            "_hard_control_state",
        )
        state = hard_control_state()

    assert state["enabled"] is True
    assert state["mode"] == "HARD_CONTROL"


def test_build_rollout_state_reflects_v1054_flags():
    with patch(
        "app.services.execution_policy_service.settings.SIGNAL_PIPELINE_V1054_ENABLED",
        True,
    ), patch(
        "app.services.execution_policy_service.settings.AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED",
        True,
    ), patch(
        "app.services.execution_policy_service.settings.NATIVE_AUDIT_V1054_ENABLED",
        True,
    ), patch(
        "app.services.execution_policy_service.settings.GOVERNANCE_HARD_GATE_ENABLED",
        False,
    ):
        rollout = ExecutionPolicyService._build_rollout_state()

    assert rollout["stage"] == "SEMI"
    assert rollout["policy_source"] == "NATIVE_EXECUTION_POLICY"


def test_build_live_execution_controls_keeps_requested_algo_when_disabled():
    with patch(
        (
            "app.services.execution_policy_service.settings."
            "EXECUTION_POLICY_HARD_CONTROL_ENABLED"
        ),
        False,
    ):
        controls = ExecutionPolicyService.build_live_execution_controls(
            {
                "action": "BUY",
                "qty": 80,
                "algo": "VWAP",
                "ref_price": 100.0,
            }
        )

    assert controls["requested_algo"] == "VWAP"
    assert controls["effective_algo"] == "VWAP"
    assert controls["broker_order_type"] == "VWAP"


def test_build_live_execution_controls_enforces_limit_on_budget_breach():
    with patch(
        (
            "app.services.execution_policy_service.settings."
            "EXECUTION_POLICY_HARD_CONTROL_ENABLED"
        ),
        True,
    ):
        controls = ExecutionPolicyService.build_live_execution_controls(
            {
                "action": "BUY",
                "qty": 600,
                "algo": "MARKET",
                "ref_price": 100.0,
            }
        )

    assert controls["control_state"]["mode"] == "HARD_CONTROL"
    assert controls["budget_breached"] is True
    assert controls["effective_algo"] == "LIMIT"
    assert controls["broker_order_type"] == "LMT"
    assert isclose(controls["limit_price"], 100.025, rel_tol=1e-9)


@pytest.mark.asyncio
async def test_feedback_applies_defensive_bias():
    service = ExecutionPolicyService()
    db = _FakeSession(
        [
            [
                SimpleNamespace(
                    total_is_bps=22.0,
                    fill_rate=0.68,
                    quality_score=61.0,
                    created_at=None,
                ),
                SimpleNamespace(
                    total_is_bps=19.0,
                    fill_rate=0.74,
                    quality_score=66.0,
                    created_at=None,
                ),
                SimpleNamespace(
                    total_is_bps=18.0,
                    fill_rate=0.79,
                    quality_score=69.0,
                    created_at=None,
                ),
            ],
            [],  # _safe_load_profile returns no persistent profile
        ]
    )

    with patch(
        (
            "app.services.execution_policy_service.settings."
            "EXECUTION_POLICY_HARD_CONTROL_ENABLED"
        ),
        True,
    ):
        controls = await service.build_live_execution_controls_with_feedback(
            cast(Any, db),
            "acc-1",
            {
                "symbol": "AAPL",
                "action": "BUY",
                "qty": 80,
                "algo": "MARKET",
                "ref_price": 100.0,
            },
        )

    assert controls["feedback_profile"]["sample_size"] == 3
    assert controls["feedback_profile"]["feedback_bias"] == "DEFENSIVE"
    assert controls["effective_algo"] == "LIMIT"
    assert controls["policy"]["feedback_bias"] == "DEFENSIVE"
    assert controls["policy"]["max_participation_rate"] < 0.4


@pytest.mark.asyncio
async def test_update_persistent_feedback_profile_tracks_running_averages():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(ExecutionPolicyProfile.__table__.create)

    service = ExecutionPolicyService()
    intent = SimpleNamespace(action="BUY", qty=120, reason=None, symbol="AAPL")

    async with session_factory() as session:
        await service.update_persistent_feedback_profile_from_execution(
            session,
            account_id="acc-1",
            symbol="AAPL",
            intent=intent,
            log=SimpleNamespace(
                total_is_bps=20.0,
                fill_rate=0.7,
                quality_score=60.0,
                algo_type="LIMIT",
                created_at=datetime(2026, 3, 10, 10, 0, 0),
            ),
        )
        await service.update_persistent_feedback_profile_from_execution(
            session,
            account_id="acc-1",
            symbol="AAPL",
            intent=intent,
            log=SimpleNamespace(
                total_is_bps=10.0,
                fill_rate=0.9,
                quality_score=80.0,
                algo_type="LIMIT",
                created_at=datetime(2026, 3, 10, 11, 0, 0),
            ),
        )
        profile = (
            (await session.execute(select(ExecutionPolicyProfile))).scalars().one()
        )

    await engine.dispose()

    assert profile.sample_size == 2
    assert profile.avg_total_is_bps == pytest.approx(15.0)
    assert profile.avg_fill_rate == pytest.approx(0.8)
    assert profile.avg_quality_score == pytest.approx(70.0)
    assert profile.last_total_is_bps == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_feedback_uses_persistent_profile_when_logs_missing():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(ExecutionPolicyProfile.__table__.create)

    service = ExecutionPolicyService()
    intent = SimpleNamespace(action="BUY", qty=180, reason=None, symbol="AAPL")

    with patch(
        (
            "app.services.execution_policy_service.settings."
            "EXECUTION_POLICY_HARD_CONTROL_ENABLED"
        ),
        True,
    ):
        async with session_factory() as session:
            await service.update_persistent_feedback_profile_from_execution(
                session,
                account_id="acc-1",
                symbol="AAPL",
                intent=intent,
                log=SimpleNamespace(
                    total_is_bps=21.0,
                    fill_rate=0.72,
                    quality_score=63.0,
                    algo_type="LIMIT",
                    created_at=datetime(2026, 3, 10, 12, 0, 0),
                ),
            )
            controls = await service.build_live_execution_controls_with_feedback(
                session,
                "acc-1",
                {
                    "symbol": "AAPL",
                    "action": "BUY",
                    "qty": 180,
                    "algo": "MARKET",
                    "ref_price": 100.0,
                },
            )

    await engine.dispose()

    assert controls["feedback_profile"]["source"] == "persistent_profile"
    assert controls["feedback_profile"]["feedback_bias"] == "DEFENSIVE"
    assert controls["persistent_profile"] is not None
    assert controls["persistent_profile"]["sample_size"] == 1
    assert controls["effective_algo"] == "LIMIT"


@pytest.mark.asyncio
async def test_get_policy_overview_includes_broker_order_id():
    service = ExecutionPolicyService()
    db = _FakeSession(
        [
            [
                SimpleNamespace(
                    id=7,
                    intent_id="intent-007",
                    order_id="broker-007",
                    symbol="AAPL",
                    action="BUY",
                    status="SUCCESS",
                    qty=50,
                    reason=None,
                    created_at=None,
                )
            ],
            [],
            [
                SimpleNamespace(
                    id=91,
                    account_id="acc-1",
                    symbol="AAPL",
                    side="BUY",
                    urgency_bucket="LOW",
                    algo_type="LIMIT",
                    sample_size=4,
                    avg_total_is_bps=11.2,
                    avg_fill_rate=0.91,
                    avg_quality_score=82.0,
                    feedback_bias="NEUTRAL",
                    recommended_algo=None,
                    limit_offset_bps=2.5,
                    participation_rate_multiplier=1.0,
                    pressure_high=False,
                    last_feedback_at=None,
                )
            ],
        ]
    )

    overview = await service.get_policy_overview(
        cast(Any, db),
        "acc-1",
        limit=5,
        order_id="broker-007",
    )

    assert overview["policies"][0]["order_id"] == "broker-007"
    assert overview["policies"][0]["persistent_profile"] is not None
    assert overview["lookup"]["match_mode"] == "order_id"
    assert overview["summary"]["persistent_profile_matches"] == 1
    assert overview["control_state"]["mode"] in {
        "OBSERVE_ONLY",
        "HARD_CONTROL",
    }
    assert overview["rollout"]["policy_source"] == "NATIVE_EXECUTION_POLICY"


@pytest.mark.asyncio
async def test_get_policy_overview_falls_back_when_order_id_misses():
    service = ExecutionPolicyService()
    db = _FakeSession(
        [
            [],
            [
                SimpleNamespace(
                    id=8,
                    intent_id="intent-008",
                    order_id="broker-008",
                    symbol="AAPL",
                    action="BUY",
                    status="SUCCESS",
                    qty=80,
                    reason=None,
                    created_at=None,
                )
            ],
            [],
            [],
        ]
    )

    overview = await service.get_policy_overview(
        cast(Any, db),
        "acc-1",
        limit=5,
        symbol="AAPL",
        action="BUY",
        order_id="missing-order",
    )

    assert overview["policies"][0]["intent_key"] == "intent-008"
    assert overview["lookup"]["requested_order_id"] == "missing-order"
    assert overview["lookup"]["match_mode"] == "fallback_filters"


@pytest.mark.asyncio
async def test_get_policy_detail_exposes_persistent_profile():
    service = ExecutionPolicyService()
    db = _FakeSession(
        [
            [
                SimpleNamespace(
                    id=11,
                    intent_id="intent-011",
                    idempotency_key="idem-011",
                    symbol="AAPL",
                    action="BUY",
                    status="SUCCESS",
                    qty=180,
                    order_id="broker-011",
                    reason="unit test",
                    created_at=datetime(2026, 3, 10, 12, 0, 0),
                    updated_at=datetime(2026, 3, 10, 12, 5, 0),
                )
            ],
            [],
            [
                SimpleNamespace(
                    id=101,
                    account_id="acc-1",
                    symbol="AAPL",
                    side="BUY",
                    urgency_bucket="LOW",
                    algo_type="LIMIT",
                    sample_size=3,
                    avg_total_is_bps=18.0,
                    avg_fill_rate=0.74,
                    avg_quality_score=65.0,
                    feedback_bias="DEFENSIVE",
                    recommended_algo="LIMIT",
                    limit_offset_bps=3.5,
                    participation_rate_multiplier=0.75,
                    pressure_high=True,
                    last_feedback_at=datetime(2026, 3, 10, 11, 55, 0),
                )
            ],
        ]
    )

    with patch(
        (
            "app.services.execution_policy_service.settings."
            "EXECUTION_POLICY_HARD_CONTROL_ENABLED"
        ),
        True,
    ):
        detail = await service.get_policy_detail(
            cast(Any, db),
            "acc-1",
            11,
        )

    assert detail is not None
    assert detail["persistent_profile"] is not None
    assert detail["persistent_profile"]["feedback_bias"] == "DEFENSIVE"
    assert detail["feedback_profile"]["source"] == "persistent_profile"
    assert detail["feedback_profile"]["recommended_algo"] == "LIMIT"
    assert detail["policy_source"] == "NATIVE_EXECUTION_POLICY"


@pytest.mark.asyncio
async def test_get_policy_detail_uses_latest_execution_quality_log_when_duplicates_exist():
    service = ExecutionPolicyService()
    db = _FakeSession(
        [
            [
                SimpleNamespace(
                    id=12,
                    intent_id="intent-012",
                    idempotency_key="idem-012",
                    symbol="AAPL",
                    action="BUY",
                    status="SUCCESS",
                    qty=220,
                    order_id="broker-012",
                    reason="duplicate log regression",
                    created_at=datetime(2026, 3, 10, 12, 0, 0),
                    updated_at=datetime(2026, 3, 10, 12, 10, 0),
                )
            ],
            [
                SimpleNamespace(
                    id=201,
                    intent_id=12,
                    algo_type="VWAP",
                    grade="C",
                    quality_score=61.0,
                    total_is_bps=19.0,
                    fill_rate=0.73,
                    time_to_fill_ms=12000,
                    arrival_price=100.0,
                    fill_price=100.4,
                    mid_price_at_order=100.2,
                    vwap_reference=100.3,
                    created_at=datetime(2026, 3, 10, 12, 1, 0),
                ),
                SimpleNamespace(
                    id=202,
                    intent_id=12,
                    algo_type="LIMIT",
                    grade="A",
                    quality_score=92.0,
                    total_is_bps=7.5,
                    fill_rate=0.98,
                    time_to_fill_ms=4000,
                    arrival_price=100.0,
                    fill_price=100.1,
                    mid_price_at_order=100.0,
                    vwap_reference=100.05,
                    created_at=datetime(2026, 3, 10, 12, 2, 0),
                ),
            ],
            [],
        ]
    )

    detail = await service.get_policy_detail(
        cast(Any, db),
        "acc-1",
        12,
    )

    assert detail is not None
    assert detail["policy"]["algo_type"] == "LIMIT"
    assert detail["execution_result"]["grade"] == "A"
    assert detail["execution_result"]["total_is_bps"] == pytest.approx(7.5)
    assert detail["execution_result"]["time_to_fill_ms"] == 4000


@pytest.mark.asyncio
async def test_get_policy_overview_prefers_latest_log_per_intent():
    service = ExecutionPolicyService()
    db = _FakeSession(
        [
            [
                SimpleNamespace(
                    id=13,
                    intent_id="intent-013",
                    order_id="broker-013",
                    symbol="AAPL",
                    action="BUY",
                    status="SUCCESS",
                    qty=120,
                    reason=None,
                    created_at=datetime(2026, 3, 10, 12, 0, 0),
                )
            ],
            [
                SimpleNamespace(
                    id=301,
                    intent_id=13,
                    algo_type="VWAP",
                    total_is_bps=15.0,
                    fill_rate=0.75,
                    quality_score=66.0,
                    created_at=datetime(2026, 3, 10, 12, 1, 0),
                ),
                SimpleNamespace(
                    id=302,
                    intent_id=13,
                    algo_type="LIMIT",
                    total_is_bps=6.0,
                    fill_rate=0.99,
                    quality_score=93.0,
                    created_at=datetime(2026, 3, 10, 12, 3, 0),
                ),
            ],
            [],
        ]
    )

    overview = await service.get_policy_overview(
        cast(Any, db),
        "acc-1",
        limit=5,
    )

    assert overview["policies"][0]["policy"]["algo_type"] == "LIMIT"
    assert overview["summary"]["avg_realized_is_bps"] == pytest.approx(6.0)
