from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.jobs.data_refresh_jobs import _collect_symbols_for_technical_refresh
from app.routers.system_monitor import _classify_source_status


def test_classify_source_status_downgrades_when_job_imminent() -> None:
    now = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)
    next_run = now + timedelta(minutes=5)

    status = _classify_source_status(
        now=now,
        requires_live_data=True,
        lag_seconds=4 * 3600,
        warn_after=45 * 60,
        critical_after=90 * 60,
        pending_next_run_at=next_run,
    )

    assert status == "WARN"


def test_classify_source_status_keeps_critical_when_no_job_pending() -> None:
    now = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)

    status = _classify_source_status(
        now=now,
        requires_live_data=True,
        lag_seconds=4 * 3600,
        warn_after=45 * 60,
        critical_after=90 * 60,
        pending_next_run_at=None,
    )

    assert status == "CRITICAL"


@pytest.mark.asyncio
async def test_collect_symbols_for_technical_refresh_merges_sources() -> None:
    class FakeResult:
        def all(self):
            return [
                SimpleNamespace(symbol="MSFT"),
                SimpleNamespace(symbol=" amd "),
                SimpleNamespace(symbol=""),
            ]

    class FakeSession:
        async def execute(self, _stmt):
            return FakeResult()

    symbols = await _collect_symbols_for_technical_refresh(
        FakeSession(),
        ["AAPL", "amd", None],
    )

    assert symbols == ["AAPL", "AMD", "MSFT"]
