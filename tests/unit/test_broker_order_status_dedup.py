from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.order_executor import OrderExecutor


class _EmptyResult:
    def scalars(self):
        return self

    def first(self):
        return None


@pytest.mark.asyncio
async def test_monitor_order_status_reuses_prefetched_status_response():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_EmptyResult())

    executor = OrderExecutor(cast(Any, session))
    executor.broker.get_order_status = AsyncMock(
        side_effect=AssertionError("broker.get_order_status should not be called when status_resp is provided")
    )

    resp = await executor.monitor_order_status(
        account_id="acc-1",
        order_id="42495319325166592",
        status_resp={"status": "NOT_FOUND", "message": "prefetched"},
    )

    assert resp["status"] == "NOT_FOUND"
    assert resp["message"] == "prefetched"
