import asyncio
from math import isclose
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.services.execution_policy_service import ExecutionPolicyService


class _FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


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

    policy = ExecutionPolicyService._derive_policy_snapshot(intent, log)

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

    pretrade = ExecutionPolicyService._derive_pretrade_cost(intent, log)

    assert isclose(pretrade["total_expected_cost_bps"], 12.4, rel_tol=1e-9)
    assert isclose(pretrade["market_impact_bps"], 5.4, rel_tol=1e-9)


def test_build_exceptions_flags_slippage_breach_and_fill_rate():
    intent = SimpleNamespace(status="SUCCESS", reason=None)
    log = SimpleNamespace(total_is_bps=26.0, fill_rate=0.52)
    policy = {"slippage_budget_bps": 18.0}

    exceptions = ExecutionPolicyService._build_exceptions(intent, log, policy)

    kinds = {item["type"] for item in exceptions}
    assert "SLIPPAGE_BUDGET_BREACH" in kinds
    assert "LOW_FILL_RATE" in kinds


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
        ]
    )

    overview = await service.get_policy_overview(
        cast(Any, db),
        "acc-1",
        limit=5,
        order_id="broker-007",
    )

    assert overview["policies"][0]["order_id"] == "broker-007"
    assert overview["lookup"]["match_mode"] == "order_id"


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
