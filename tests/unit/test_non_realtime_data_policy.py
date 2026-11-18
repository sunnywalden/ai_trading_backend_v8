from datetime import datetime, timedelta, timezone

import pytest

from app.services.non_realtime_data_policy import NonRealtimeDataPolicyService
from app.routers import system_monitor
from types import SimpleNamespace


def test_runtime_signal_generation_policy_defaults_to_cache_only():
    policy = NonRealtimeDataPolicyService.runtime_signal_generation()

    assert policy.context == "runtime_signal_generation"
    assert policy.historical_cache_only is True
    assert policy.key_statistics_cache_only is True
    assert policy.fundamental_cache_only is True


def test_scheduled_refresh_policy_allows_live_fetch():
    policy = NonRealtimeDataPolicyService.scheduled_refresh()

    assert policy.context == "scheduled_refresh"
    assert policy.historical_cache_only is False
    assert policy.key_statistics_cache_only is False
    assert policy.fundamental_cache_only is False


@pytest.mark.asyncio
async def test_non_realtime_policy_runtime_status_aggregates_job_payloads(monkeypatch):
    payloads = {
        "non_realtime_data:job_status:historical_bars_cache": {
            "job_key": "historical_bars_cache",
            "success": True,
            "success_count": 10,
            "failure_count": 0,
            "last_run_at": "2026-03-13T08:00:00+00:00",
        },
        "non_realtime_data:job_status:key_statistics_cache": {
            "job_key": "key_statistics_cache",
            "success": True,
            "success_count": 8,
            "failure_count": 0,
            "last_run_at": "2026-03-13T08:05:00+00:00",
        },
        "non_realtime_data:job_status:fundamental_data_cache": {
            "job_key": "fundamental_data_cache",
            "success": False,
            "success_count": 6,
            "failure_count": 2,
            "last_run_at": "2026-03-13T08:10:00+00:00",
        },
    }

    async def fake_cache_get(key):
        return payloads.get(key)

    monkeypatch.setattr("app.services.non_realtime_data_policy.cache.get", fake_cache_get)

    status = await NonRealtimeDataPolicyService.get_runtime_status()

    assert status["runtime_signal_generation"]["historical_cache_only"] is True
    assert status["jobs"]["fundamental_data_cache"]["failure_count"] == 2


@pytest.mark.asyncio
async def test_system_monitor_exposes_non_realtime_policy_service(monkeypatch):
    recent_run = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    async def fake_policy_status():
        return {
            "runtime_signal_generation": {
                "context": "runtime_signal_generation",
                "historical_cache_only": True,
                "key_statistics_cache_only": True,
                "fundamental_cache_only": True,
            },
            "runtime_advisory": {
                "context": "runtime_advisory",
                "historical_cache_only": True,
                "key_statistics_cache_only": True,
                "fundamental_cache_only": True,
            },
            "scheduled_refresh": {
                "context": "scheduled_refresh",
                "historical_cache_only": False,
                "key_statistics_cache_only": False,
                "fundamental_cache_only": False,
            },
            "jobs": {
                "historical_bars_cache": {
                    "success": True,
                    "success_count": 12,
                    "failure_count": 0,
                    "last_run_at": recent_run,
                },
                "key_statistics_cache": {
                    "success": True,
                    "success_count": 12,
                    "failure_count": 0,
                    "last_run_at": recent_run,
                },
                "fundamental_data_cache": {
                    "success": True,
                    "success_count": 12,
                    "failure_count": 0,
                    "last_run_at": recent_run,
                },
            },
        }

    monkeypatch.setattr(
        "app.routers.system_monitor.NonRealtimeDataPolicyService.get_runtime_status",
        fake_policy_status,
    )
    async def fake_lifecycle_overview(db, window_minutes, include_details):
        return SimpleNamespace(
            headline=SimpleNamespace(warn_stage_count=0, critical_stage_count=0, exception_count=0, p95_stage_seconds=0.0),
            meta=SimpleNamespace(generated_at=system_monitor._now()),
        )

    monkeypatch.setattr(
        "app.routers.system_monitor._build_lifecycle_overview",
        fake_lifecycle_overview,
    )

    async def fake_run_all_checks(db):
        return SimpleNamespace(
            overall_status="OK",
            generated_at=system_monitor._now().isoformat(),
            checks=[],
        )

    async def fake_snapshot(db):
        return SimpleNamespace(as_of=system_monitor._now())

    async def fake_monitoring_health():
        return {"status": "healthy", "warning": 0, "critical": 0}

    monkeypatch.setattr("app.routers.system_monitor.autonomy_health_monitor.run_all_checks", fake_run_all_checks)
    monkeypatch.setattr("app.routers.system_monitor.situational_awareness_service.get_snapshot", fake_snapshot)
    monkeypatch.setattr("app.routers.system_monitor.monitoring_health_check", fake_monitoring_health)
    monkeypatch.setattr("app.routers.system_monitor.redis_client", None)

    class FakeDb:
        async def execute(self, stmt):
            return SimpleNamespace()

    _modules, services, _timeline, _failures = await system_monitor._build_service_payload(
        db=FakeDb(),
        window_minutes=60,
    )

    policy_service = next(service for service in services if service.service_key == "non_realtime_data_policy")
    assert policy_service.status == "HEALTHY"
    assert any(tag.startswith("runtime-signal-cache-only:True") for tag in policy_service.tags)