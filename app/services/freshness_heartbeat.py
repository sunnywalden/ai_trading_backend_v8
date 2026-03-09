"""freshness_heartbeat.py — freshness 心跳通用工具。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.cache import cache


def normalize_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


async def read_heartbeat_timestamp(key: str) -> datetime | None:
    try:
        raw = await cache.get(key, is_json=False)
        if not raw:
            return None
        return normalize_timestamp(datetime.fromisoformat(str(raw)))
    except Exception:
        return None


async def write_heartbeat_timestamp(key: str, ts: datetime, *, ttl_seconds: int = 3600) -> None:
    normalized = normalize_timestamp(ts)
    if normalized is None:
        return
    try:
        await cache.set(
            key,
            normalized.isoformat(),
            expire=ttl_seconds,
            is_json=False,
        )
    except Exception:
        pass


def max_available_timestamp(*values: datetime | None) -> datetime | None:
    candidates = [normalize_timestamp(value) for value in values if value is not None]
    return max(candidates, default=None)
