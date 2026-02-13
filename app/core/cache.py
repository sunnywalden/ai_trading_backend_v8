import json
import pickle
from typing import Any, Optional, Union
from datetime import timedelta
from app.models.db import redis_client

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
                return json.loads(data)
            except:
                return data
        return data

    async def set(self, key: str, value: Any, expire: Union[int, timedelta] = None, is_json: bool = True) -> bool:
        if not redis_client:
            return False
        
        if is_json:
            data = json.dumps(value)
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
