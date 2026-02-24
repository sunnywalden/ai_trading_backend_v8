"""
运行时动态配置

优先级：Redis 持久化值  >  环境变量 / 默认值

说明：
  - 应用启动时，从 .env / 环境变量读取 AI_AUTONOMY_LEVEL 作为初始默认值。
  - 通过 API（PUT /autonomy/level）修改后，新值写入 Redis（无过期时间）。
  - 任何地方调用 get_autonomy_level() 都会优先返回 Redis 中的持久化值。
  - Redis 不可用时，自动降级到 settings.AI_AUTONOMY_LEVEL（进程内值）。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Redis 持久化 key
_AUTONOMY_LEVEL_KEY = "runtime:ai_autonomy_level"

_VALID_AUTONOMY_LEVELS = {"FULL", "SEMI", "ADVISORY"}


async def get_autonomy_level() -> str:
    """
    获取当前有效的 AI 自主级别。

    读取优先级：
      1. Redis 持久化值（非空字符串）
      2. settings.AI_AUTONOMY_LEVEL（进程内值 / .env 初始值）
    """
    from app.core.cache import cache
    from app.core.config import settings

    try:
        persisted: Optional[str] = await cache.get(_AUTONOMY_LEVEL_KEY, is_json=False)
        if persisted and isinstance(persisted, str):
            level = persisted.strip().upper()
            if level in _VALID_AUTONOMY_LEVELS:
                return level
    except Exception as e:
        logger.debug(f"[runtime_config] Redis unavailable, using env default: {e}")

    return settings.AI_AUTONOMY_LEVEL


async def set_autonomy_level(level: str) -> bool:
    """
    设置 AI 自主级别并持久化到 Redis。

    同时更新进程内 settings.AI_AUTONOMY_LEVEL，确保本次请求后立即生效。

    Args:
        level: "FULL" | "SEMI" | "ADVISORY"

    Returns:
        True 表示 Redis 持久化成功；False 表示 Redis 不可用（进程内已更新）。
    """
    from app.core.cache import cache
    from app.core.config import settings

    # 1. 更新进程内值（立即生效）
    settings.AI_AUTONOMY_LEVEL = level

    # 2. 持久化到 Redis（expire=None 即永不过期，重启后仍有效）
    try:
        ok = await cache.set(_AUTONOMY_LEVEL_KEY, level, expire=None, is_json=False)
        logger.info(f"[runtime_config] AI_AUTONOMY_LEVEL persisted to Redis: {level}")
        return bool(ok)
    except Exception as e:
        logger.warning(f"[runtime_config] Redis persist failed (in-memory updated): {e}")
        return False


async def clear_autonomy_level_override() -> bool:
    """
    清除 Redis 中的持久化值，使系统回退到 .env 中的 AI_AUTONOMY_LEVEL。
    """
    from app.core.cache import cache

    try:
        await cache.delete(_AUTONOMY_LEVEL_KEY)
        logger.info("[runtime_config] AI_AUTONOMY_LEVEL override cleared, reverting to env default")
        return True
    except Exception as e:
        logger.warning(f"[runtime_config] Failed to clear level override: {e}")
        return False
