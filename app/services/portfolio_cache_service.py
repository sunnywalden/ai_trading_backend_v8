"""Portfolio-facing cache invalidation helpers.

集中管理会影响前端持仓视图一致性的缓存前缀，避免不同路由/任务各自维护。
"""

from __future__ import annotations

from typing import Iterable

from app.core.cache import cache
from app.models.db import redis_client


async def _delete_prefixed_keys(prefixes: Iterable[str]) -> None:
    if not redis_client:
        return

    unique_prefixes = [prefix for prefix in dict.fromkeys(prefixes) if prefix]
    if not unique_prefixes:
        return

    keys_to_delete: list[str] = []
    for prefix in unique_prefixes:
        try:
            keys = await redis_client.keys(f"{cache.prefix}{prefix}*")
        except Exception:
            continue
        if keys:
            keys_to_delete.extend(keys)

    if not keys_to_delete:
        return

    try:
        await redis_client.delete(*dict.fromkeys(keys_to_delete))
    except Exception:
        pass


async def invalidate_positions_assessment_cache(account_id: str) -> None:
    """清理持仓评估缓存。"""
    if not account_id:
        return
    await _delete_prefixed_keys([f"positions_assessment:{account_id}:"])


async def invalidate_morning_brief_cache(account_id: str) -> None:
    """清理早间简报缓存。"""
    if not account_id:
        return
    await _delete_prefixed_keys([f"morning_brief:{account_id}:"])


async def invalidate_portfolio_view_caches(account_id: str) -> None:
    """清理所有与持仓视图一致性强相关的缓存。"""
    if not account_id:
        return
    await _delete_prefixed_keys(
        [
            f"positions_assessment:{account_id}:",
            f"morning_brief:{account_id}:",
        ]
    )