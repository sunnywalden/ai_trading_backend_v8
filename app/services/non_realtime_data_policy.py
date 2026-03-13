from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class NonRealtimeDataPolicy:
    context: str
    historical_cache_only: bool
    key_statistics_cache_only: bool
    fundamental_cache_only: bool


class NonRealtimeDataPolicyService:
    """统一定义运行时对非实时数据的访问策略。"""

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
