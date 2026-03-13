from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.cache import cache


@dataclass(frozen=True)
class NonRealtimeDataPolicy:
    context: str
    historical_cache_only: bool
    key_statistics_cache_only: bool
    fundamental_cache_only: bool


class NonRealtimeDataPolicyService:
    """统一定义运行时对非实时数据的访问策略。"""

    _JOB_STATUS_KEY_PREFIX = "non_realtime_data:job_status:"

    @classmethod
    def _job_status_cache_key(cls, job_key: str) -> str:
        return f"{cls._JOB_STATUS_KEY_PREFIX}{job_key}"

    @staticmethod
    def runtime_signal_generation() -> NonRealtimeDataPolicy:
        cache_only = bool(settings.RUNTIME_NON_REALTIME_CACHE_ONLY)
        return NonRealtimeDataPolicy(
            context="runtime_signal_generation",
            historical_cache_only=cache_only,
            key_statistics_cache_only=cache_only,
            fundamental_cache_only=cache_only,
        )

    @staticmethod
    def runtime_advisory() -> NonRealtimeDataPolicy:
        cache_only = bool(settings.ADVISORY_NON_REALTIME_CACHE_ONLY)
        return NonRealtimeDataPolicy(
            context="runtime_advisory",
            historical_cache_only=cache_only,
            key_statistics_cache_only=cache_only,
            fundamental_cache_only=cache_only,
        )

    @staticmethod
    def scheduled_refresh() -> NonRealtimeDataPolicy:
        return NonRealtimeDataPolicy(
            context="scheduled_refresh",
            historical_cache_only=False,
            key_statistics_cache_only=False,
            fundamental_cache_only=False,
        )

    @classmethod
    async def record_job_status(
        cls,
        job_key: str,
        *,
        success: bool,
        success_count: int | None = None,
        failure_count: int | None = None,
        error: str | None = None,
    ) -> None:
        payload = {
            "job_key": job_key,
            "success": success,
            "success_count": int(success_count or 0),
            "failure_count": int(failure_count or 0),
            "error": error,
            "last_run_at": datetime.now(UTC).isoformat(),
        }
        await cache.set(cls._job_status_cache_key(job_key), payload, expire=7 * 24 * 3600)

    @classmethod
    async def get_runtime_status(cls) -> dict[str, Any]:
        job_keys = [
            "historical_bars_cache",
            "key_statistics_cache",
            "fundamental_data_cache",
        ]
        jobs: dict[str, Any] = {}
        for job_key in job_keys:
            payload = await cache.get(cls._job_status_cache_key(job_key))
            jobs[job_key] = payload if isinstance(payload, dict) else None

        return {
            "runtime_signal_generation": cls.runtime_signal_generation().__dict__,
            "runtime_advisory": cls.runtime_advisory().__dict__,
            "scheduled_refresh": cls.scheduled_refresh().__dict__,
            "jobs": jobs,
        }
