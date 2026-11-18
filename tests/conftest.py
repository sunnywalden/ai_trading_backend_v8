"""Offline unit-test defaults: no production secrets and no live Redis."""

from __future__ import annotations

import fnmatch
import os

os.environ.setdefault("ADMIN_PASSWORD", "unit-test-admin-password")
os.environ.setdefault("JWT_SECRET_KEY", "unit-test-jwt-secret")


class MemoryRedis:
    """In-memory stand-in so unit tests do not open a socket."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str):
        return self._data.get(key)

    async def set(self, key: str, value, ex=None, nx: bool = False):
        if nx and key in self._data:
            return None
        self._data[key] = value
        return True

    async def setex(self, key: str, ttl: int, value):
        self._data[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                removed += 1
        return removed

    async def exists(self, key: str) -> int:
        return 1 if key in self._data else 0

    async def keys(self, pattern: str) -> list[str]:
        return [key for key in self._data if fnmatch.fnmatch(key, pattern)]

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _install_memory_redis() -> None:
    from app.models import db as db_mod

    db_mod.redis_client = MemoryRedis()


_install_memory_redis()


import pytest


@pytest.fixture(autouse=True)
def offline_dummy_broker(monkeypatch):
    """Unit tests must not construct a live broker client."""
    from app.broker import factory
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUNTIME_ALLOW_DUMMY_BROKER", True, raising=False)
    factory._broker_instance = None
    yield
    factory._broker_instance = None
