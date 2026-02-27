import json
import pickle
import math
from typing import Any, Optional, Union
from datetime import timedelta
from app.models.db import redis_client


def _sanitize_for_json(value: Any) -> Any:
    """递归清洗 JSON 不兼容值（NaN/Inf/numpy 标量）。"""
    if value is None:
        return None

    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value

    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_for_json(v) for v in value)

    # numpy 标量兼容：float32/float64/int32/int64 等
    module_name = type(value).__module__ or ""
    if module_name == "numpy" or module_name.startswith("numpy."):
        try:
            py_value = value.item() if hasattr(value, "item") else value
            if isinstance(py_value, float) and (math.isnan(py_value) or math.isinf(py_value)):
                return None
            return py_value
        except Exception:
            try:
                f = float(value)
                return None if (math.isnan(f) or math.isinf(f)) else f
            except Exception:
                return None

    return value

class RedisCache:
    """
    Redis 缓存封装类
    """
    def __init__(self, prefix: str = "ai_trading:"):
        self.prefix = prefix

    def _make_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def get(self, key: str, is_json: bool = True) -> Any:
        if not redis_client:
            return None
        
        data = await redis_client.get(self._make_key(key))
        if data is None:
            return None
        
        if is_json:
            try:
                # 兼容历史脏缓存（可能包含 NaN）
                parsed = json.loads(data)
                return _sanitize_for_json(parsed)
            except:
                return data
        return data

    async def set(self, key: str, value: Any, expire: Union[int, timedelta, None] = None, is_json: bool = True) -> bool:
        if not redis_client:
            return False
        
        if is_json:
            clean_value = _sanitize_for_json(value)
            data = json.dumps(clean_value, allow_nan=False)
        else:
            data = str(value)
            
        return await redis_client.set(self._make_key(key), data, ex=expire)

    async def delete(self, key: str) -> bool:
        if not redis_client:
            return False
        return await redis_client.delete(self._make_key(key)) > 0

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if not redis_client:
            return False
        return await redis_client.exists(self._make_key(key)) > 0

    async def flush_all(self) -> bool:
        if not redis_client:
            return False
        # 慎用，这会清除所有带有前缀的 key
        keys = await redis_client.keys(f"{self.prefix}*")
        if keys:
            return await redis_client.delete(*keys) > 0
        return True

# 全局缓存实例
cache = RedisCache()
