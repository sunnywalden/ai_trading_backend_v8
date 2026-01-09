from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from typing import AsyncGenerator
import redis.asyncio as redis
from app.core.config import settings

Base = declarative_base()

# 创建异步数据库引擎
# 如果是 SQLite，不需要 pool_pre_ping 等参数，但 MySQL 强烈建议
engine_kwargs = {
    "echo": False,
    "future": True,
}

if settings.DB_TYPE == "mysql":
    engine_kwargs.update({
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "pool_size": 10,
        "max_overflow": 20,
    })

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# 创建异步会话工厂
SessionLocal = async_sessionmaker(
    engine, 
    expire_on_commit=False, 
    class_=AsyncSession
)

# 创建 Redis 客户端
redis_client = None
if settings.REDIS_ENABLED:
    redis_client = redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库异步会话的依赖项"""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_redis():
    """获取 Redis 客户端的依赖项"""
    return redis_client
