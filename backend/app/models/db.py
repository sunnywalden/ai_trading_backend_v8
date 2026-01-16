from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
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


async def ensure_mysql_indexes() -> None:
    """启动时检查/创建MySQL索引（仅MySQL生效）。"""
    if settings.DB_TYPE != "mysql":
        return

    index_specs = [
        (
            "ix_behavior_account_symbol_window",
            "symbol_behavior_stats",
            "CREATE INDEX ix_behavior_account_symbol_window ON symbol_behavior_stats (account_id, symbol, window_days)",
        ),
        (
            "ix_risk_profile_symbol_market",
            "symbol_risk_profile",
            "CREATE INDEX ix_risk_profile_symbol_market ON symbol_risk_profile (symbol, market)",
        ),
        (
            "ix_trend_account_symbol_timeframe_ts",
            "position_trend_snapshots",
            "CREATE INDEX ix_trend_account_symbol_timeframe_ts ON position_trend_snapshots (account_id, symbol, timeframe, timestamp)",
        ),
    ]

    async with engine.begin() as conn:
        for index_name, table_name, create_sql in index_specs:
            result = await conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.statistics
                    WHERE table_schema = DATABASE()
                      AND table_name = :table_name
                      AND index_name = :index_name
                    """
                ),
                {"table_name": table_name, "index_name": index_name},
            )
            exists = (result.scalar() or 0) > 0
            if not exists:
                await conn.execute(text(create_sql))


async def ensure_mysql_tables() -> None:
    """启动时检查/创建关键MySQL表（仅MySQL生效）。"""
    if settings.DB_TYPE != "mysql":
        return

    table_specs = [
        (
            "trading_plan",
            """
            CREATE TABLE trading_plan (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              account_id VARCHAR(64) NOT NULL,
              symbol VARCHAR(32) NOT NULL,
              entry_price DECIMAL(20, 6) NOT NULL,
              stop_loss DECIMAL(20, 6) NOT NULL,
              take_profit DECIMAL(20, 6) NOT NULL,
              target_position DECIMAL(10, 4) NOT NULL,
              plan_status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
              plan_tags JSON NULL,
              valid_from DATETIME NULL,
              valid_until DATETIME NULL,
              notes VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_plan_account_status (account_id, plan_status),
              INDEX idx_plan_symbol (symbol),
              INDEX idx_plan_valid_until (valid_until)
            )
            """,
        ),
    ]

    async with engine.begin() as conn:
        for table_name, create_sql in table_specs:
            result = await conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
            exists = (result.scalar() or 0) > 0
            if not exists:
                await conn.execute(text(create_sql))

async def get_redis():
    """获取 Redis 客户端的依赖项"""
    return redis_client
