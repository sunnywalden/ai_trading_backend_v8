import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.services.order_book_service import OrderBookService


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
    def __init__(self, intents):
        self._intents = intents

    async def execute(self, _stmt):
        await asyncio.sleep(0)
        return _FakeExecuteResult(self._intents)


@pytest.mark.asyncio
async def test_resolve_execution_refs_prefers_exact_intent_id_match():
    service = OrderBookService()
    resolver = OrderBookService.__dict__["_resolve_execution_refs"]
    db = _FakeSession(
        [
            SimpleNamespace(
                id=101,
                intent_id="intent-001",
                order_id="broker-001",
                signal_id="sig-001",
                signal_db_id=11,
            )
        ]
    )
    plan = SimpleNamespace(
        id=1,
        account_id="acc-1",
        plan_tags={
            "execution_intent_id": "intent-001",
            "order_id": "stale-order",
        },
        provenance_snapshot={},
    )

    resolved = await resolver(service, cast(Any, db), cast(Any, [plan]))

    assert resolved[1]["execution_intent_db_id"] == 101
    assert resolved[1]["execution_intent_key"] == "intent-001"
    assert resolved[1]["broker_order_id"] == "broker-001"


@pytest.mark.asyncio
async def test_resolve_execution_refs_falls_back_to_order_id():
    service = OrderBookService()
    resolver = OrderBookService.__dict__["_resolve_execution_refs"]
    db = _FakeSession(
        [
            SimpleNamespace(
                id=202,
                intent_id="intent-legacy",
                order_id="broker-legacy",
                signal_id="sig-legacy",
                signal_db_id=22,
            )
        ]
    )
    plan = SimpleNamespace(
        id=2,
        account_id="acc-2",
        plan_tags={"order_id": "broker-legacy"},
        provenance_snapshot={"execution_ref": {"signal_id": "sig-legacy"}},
    )

    resolved = await resolver(service, cast(Any, db), cast(Any, [plan]))

    assert resolved[2]["execution_intent_db_id"] == 202
    assert resolved[2]["execution_intent_key"] == "intent-legacy"
    assert resolved[2]["broker_order_id"] == "broker-legacy"
