from typing import AsyncGenerator

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

Base = declarative_base()

# 创建异步数据库引擎
# 如果是 SQLite，不需要 pool_pre_ping 等参数，但 MySQL 强烈建议
engine_kwargs = {
    "echo": False,
    "future": True,
}

if settings.DB_TYPE == "mysql":
    engine_kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "pool_size": 10,
            "max_overflow": 20,
        }
    )

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# 创建异步会话工厂
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# 创建 Redis 客户端
redis_client = None
if settings.REDIS_ENABLED:
    redis_client = redis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库异步会话的依赖项"""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


from contextlib import asynccontextmanager


@asynccontextmanager
async def get_session_ctx():
    """独立 session 上下文管理器，供后台任务使用（不依赖 FastAPI DI）。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
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
        (
            "ix_signals_account_origin_status",
            "trading_signals",
            "CREATE INDEX ix_signals_account_origin_status ON trading_signals (account_id, signal_origin_mode, status)",
        ),
        (
            "ix_signals_origin_generated",
            "trading_signals",
            "CREATE INDEX ix_signals_origin_generated ON trading_signals (signal_origin_mode, generated_at)",
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

    # 导入所有模型，确保它们注册到 Base.metadata
    import app.models.algo_execution_task  # noqa: F401
    import app.models.audit_log  # noqa: F401
    import app.models.autonomy_audit_log  # noqa: F401

    # V10 新增
    import app.models.backtest_task  # noqa: F401
    import app.models.copilot_message  # noqa: F401
    import app.models.equity_snapshot  # noqa: F401
    import app.models.etf_watchlist  # V10.1: ETF自选池
    import app.models.execution_intent  # V10.3.2: 执行幂等意图
    import app.models.execution_policy_profile  # V10.5.3: 执行反馈画像
    import app.models.execution_slice  # V10.4.4: 执行切片
    import app.models.fsm_transition_log  # V10.3: FSM事件日志

    # V11.0.1 新增模型
    import app.models.improvement_candidate  # noqa: F401
    import app.models.market_universe_symbol  # 机会扫描本地全量股票池
    import app.models.meta_state_snapshot  # noqa: F401
    import app.models.notification  # noqa: F401
    import app.models.paper_account  # noqa: F401
    import app.models.portfolio_snapshot  # noqa: F401
    import app.models.position  # V10.4.4: 仓位聚合根
    import app.models.position_eval_task  # noqa: F401
    import app.models.position_lifecycle_event  # V10.4.4: 生命周期事件
    import app.models.price_alert  # noqa: F401

    # 持仓评估任务
    import app.models.task_config as task_cfg  # noqa: F401
    import app.models.trade_journal  # noqa: F401
    import app.models.trade_pnl_attribution  # noqa: F401
    import app.models.trading_plan  # noqa: F401

    # 使用 SQLAlchemy metadata.create_all 自动创建所有缺失的表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_mysql_schema_updates() -> None:
    """启动时检查并修复数据库表结构变更（如缺少的列）。"""
    if settings.DB_TYPE != "mysql":
        return

    from app.models.autonomy_audit_log import AutonomyAuditLog
    from app.models.copilot_message import CopilotMessage
    from app.models.trading_plan import TradingPlan

    trading_plan_table = TradingPlan.__tablename__
    autonomy_audit_log_table = AutonomyAuditLog.__tablename__
    copilot_messages_table = CopilotMessage.__tablename__

    def _trading_plan_add_column(definition_sql: str) -> str:
        return f"ALTER TABLE {trading_plan_table} ADD COLUMN {definition_sql}"

    def _autonomy_audit_log_add_column(definition_sql: str) -> str:
        return f"ALTER TABLE {autonomy_audit_log_table} ADD COLUMN {definition_sql}"

    # 定义需要检查的列更新
    # 格式: (table_name, column_name, add_column_sql)
    column_updates = [
        (
            "trading_signals",
            "quantity_mode",
            "ALTER TABLE trading_signals ADD COLUMN quantity_mode VARCHAR(16) NULL COMMENT 'V10.3.2: 数量语义模式 PCT_EQUITY/ABS_SHARES'",
        ),
        (
            "trading_signals",
            "quantity_value",
            "ALTER TABLE trading_signals ADD COLUMN quantity_value FLOAT NULL COMMENT 'V10.3.2: 数量语义原始值'",
        ),
        (
            "trading_signals",
            "pnl",
            "ALTER TABLE trading_signals ADD COLUMN pnl FLOAT NULL COMMENT '盈亏（绝对金额）'",
        ),
        (
            "trading_signals",
            "pnl_pct",
            "ALTER TABLE trading_signals ADD COLUMN pnl_pct FLOAT NULL COMMENT '盈亏百分比'",
        ),
        (
            "trading_signals",
            "is_winner",
            "ALTER TABLE trading_signals ADD COLUMN is_winner VARCHAR(8) NULL COMMENT 'YES/NO - 是否盈利交易'",
        ),
        (
            "trading_signals",
            "signal_origin_mode",
            "ALTER TABLE trading_signals ADD COLUMN signal_origin_mode VARCHAR(16) NULL COMMENT 'V10.5.4: REAL/SYNTHETIC/BACKFILL'",
        ),
        (
            trading_plan_table,
            "plan_type",
            _trading_plan_add_column(
                "plan_type VARCHAR(16) NOT NULL DEFAULT 'MANUAL' "
                "COMMENT 'V10.1: 计划类型'"
            ),
        ),
        (
            trading_plan_table,
            "plan_status",
            _trading_plan_add_column(
                "plan_status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' "
                "COMMENT 'V10.1: 计划状态'"
            ),
        ),
        (
            trading_plan_table,
            "plan_tags",
            _trading_plan_add_column("plan_tags JSON NULL COMMENT 'V10.1: 扩展标签'"),
        ),
        (
            trading_plan_table,
            "target_position",
            _trading_plan_add_column(
                "target_position DECIMAL(10, 4) NOT NULL DEFAULT 0.0 "
                "COMMENT 'V10.1: 目标仓位'"
            ),
        ),
        (
            trading_plan_table,
            "valid_from",
            _trading_plan_add_column(
                "valid_from DATETIME NULL COMMENT 'V10.1: 有效期开始'"
            ),
        ),
        (
            trading_plan_table,
            "valid_until",
            _trading_plan_add_column(
                "valid_until DATETIME NULL COMMENT 'V10.1: 有效期截止'"
            ),
        ),
        # V10.3: 交易可观测性字段
        (
            trading_plan_table,
            "direction",
            _trading_plan_add_column(
                "direction VARCHAR(4) NULL COMMENT 'V10.3: BUY/SELL'"
            ),
        ),
        (
            trading_plan_table,
            "confidence",
            _trading_plan_add_column(
                "confidence DECIMAL(5,2) NULL COMMENT 'V10.3: AI置信度'"
            ),
        ),
        (
            trading_plan_table,
            "reasoning",
            _trading_plan_add_column("reasoning TEXT NULL COMMENT 'V10.3: AI决策摘要'"),
        ),
        (
            trading_plan_table,
            "autonomy_action",
            _trading_plan_add_column(
                "autonomy_action VARCHAR(20) NULL "
                "COMMENT 'V10.3: AUTO_EXECUTE/PENDING_CONFIRM'"
            ),
        ),
        (
            trading_plan_table,
            "source",
            _trading_plan_add_column(
                "source VARCHAR(20) NULL "
                "COMMENT 'V10.3: AI_AUTONOMOUS/AI_ADVISORY/MANUAL'"
            ),
        ),
        (
            trading_plan_table,
            "pipeline_stage",
            _trading_plan_add_column(
                "pipeline_stage SMALLINT NULL COMMENT 'V10.3: Pipeline阶段0-16'"
            ),
        ),
        (
            trading_plan_table,
            "stage_entered_at",
            _trading_plan_add_column(
                "stage_entered_at DATETIME NULL COMMENT 'V10.3: 进入当前阶段时间'"
            ),
        ),
        (
            trading_plan_table,
            "stage_history",
            _trading_plan_add_column(
                "stage_history JSON NULL COMMENT 'V10.3: 阶段历史'"
            ),
        ),
        (
            trading_plan_table,
            "provenance_snapshot",
            _trading_plan_add_column(
                "provenance_snapshot JSON NULL COMMENT 'V10.3: 决策溯源快照'"
            ),
        ),
        (
            trading_plan_table,
            "position_fsm_state",
            _trading_plan_add_column(
                "position_fsm_state VARCHAR(20) NULL COMMENT 'V10.3: 持仓FSM状态'"
            ),
        ),
        # V10.2-M1: 审计日志体制上下文字段（兼容历史库缺列）
        (
            autonomy_audit_log_table,
            "regime_at_decision",
            _autonomy_audit_log_add_column(
                "regime_at_decision VARCHAR(32) NULL COMMENT 'V10.2: 决策时市场体制'"
            ),
        ),
        (
            autonomy_audit_log_table,
            "regime_confidence",
            _autonomy_audit_log_add_column(
                "regime_confidence FLOAT NULL COMMENT 'V10.2: 体制置信度'"
            ),
        ),
    ]

    async with engine.begin() as conn:
        for table_name, column_name, add_sql in column_updates:
            try:
                # 1. 检查表是否存在
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
                if (result.scalar() or 0) == 0:
                    continue

                # 2. 检查列是否存在
                result = await conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.columns 
                        WHERE table_schema = DATABASE() 
                        AND table_name = :table_name 
                        AND column_name = :column_name
                        """
                    ),
                    {"table_name": table_name, "column_name": column_name},
                )
                exists = (result.scalar() or 0) > 0

                # 3. 如果不存在则添加
                if not exists:
                    await conn.execute(text(add_sql))
            except Exception:
                # 忽略错误，避免阻断启动
                pass

        # 枚举扩容修复：trading_signals.status 增加 SKIPPED（仅 MySQL ENUM 生效）
        try:
            result = await conn.execute(
                text(
                    """
                    SELECT COLUMN_TYPE
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = 'trading_signals'
                      AND column_name = 'status'
                    """
                )
            )
            row = result.fetchone()
            column_type = (row[0] or "") if row else ""
            if (
                column_type.lower().startswith("enum(")
                and "'SKIPPED'" not in column_type
            ):
                await conn.execute(
                    text(
                        """
                        ALTER TABLE trading_signals
                        MODIFY COLUMN status ENUM(
                            'GENERATED','VALIDATED','REJECTED','QUEUED','EXECUTING','EXECUTED','FAILED','SKIPPED','CANCELLED','EXPIRED'
                        ) NOT NULL DEFAULT 'GENERATED'
                        """
                    )
                )
        except Exception:
            pass

        # 列类型修复（已有列的长度/类型扩展）
        # 格式: (table, column, min_char_length, modify_sql)
        column_type_fixes = [
            (
                copilot_messages_table,
                "role",
                16,
                f"ALTER TABLE {copilot_messages_table} MODIFY COLUMN role VARCHAR(16) NOT NULL COMMENT 'user/assistant/system'",
            ),
        ]
        for table_name, column_name, min_length, modify_sql in column_type_fixes:
            try:
                result = await conn.execute(
                    text(
                        """
                        SELECT CHARACTER_MAXIMUM_LENGTH
                        FROM information_schema.columns
                        WHERE table_schema = DATABASE()
                        AND table_name = :table_name
                        AND column_name = :column_name
                        """
                    ),
                    {"table_name": table_name, "column_name": column_name},
                )
                row = result.fetchone()
                if row and (row[0] or 0) < min_length:
                    await conn.execute(text(modify_sql))
            except Exception:
                pass


async def get_redis():
    """获取 Redis 客户端的依赖项"""
    return redis_client


async def close_db_resources() -> None:
    """显式关闭数据库与 Redis 资源（适用于独立脚本退出前调用）。"""
    try:
        await engine.dispose()
    except Exception:
        pass

    if redis_client:
        try:
            await redis_client.close()
        except Exception:
            pass
