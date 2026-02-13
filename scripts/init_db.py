"""
数据库初始化脚本

创建所有必需的数据库表并预置内置策略
"""
import asyncio
from datetime import datetime
from typing import Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db import Base, SessionLocal, engine
from app.models.symbol_behavior_stats import SymbolBehaviorStats
from app.models.symbol_risk_profile import SymbolRiskProfile
from app.models.macro_risk import MacroRiskScore, MacroIndicator, GeopoliticalEvent
from app.models.technical_indicator import TechnicalIndicator
from app.models.fundamental_data import FundamentalData
from app.models.position_score import PositionScore
from app.models.position_trend_snapshot import PositionTrendSnapshot
from app.models.symbol_profile_cache import SymbolProfileCache
from app.models.strategy import Strategy
from app.models.trading_signal import TradingSignal, SignalPerformance
from app.models.trading_plan import TradingPlan
# V9: 个人交易相关模型
from app.models.price_alert import PriceAlert, AlertHistory
from app.models.equity_snapshot import EquitySnapshot
from app.models.trade_journal import TradeJournal
from app.models.trade_pnl_attribution import TradePnlAttribution
from app.models.notification import NotificationLog
from app.models.audit_log import AuditLog

DEFAULT_BUILTIN_STRATEGIES = [
    {
        "name": "事件驱动趋势发现",
        "style": "事件驱动",
        "description": "监控重要事件（财报、管理层变动、宏观数据）并结合 15 分钟趋势突破信号创造快速行动机会。",
        "is_builtin": True,
        "is_active": True,
        "tags": ["event-driven", "momentum", "alpha"],
        "default_params": {
            "cycle_minutes": 15,
            "min_score": 0.8,
            "max_position": 0.25,
            "notify_channels": ["slack-trading"],
        },
        "signal_sources": {"price": "breakout", "events": ["earnings", "guidance", "macro"]},
        "risk_profile": {"max_drawdown": 0.08, "stop_loss": 0.04},
    },
    {
        "name": "日内切换突破",
        "style": "日内交易",
        "description": "追踪 5-30 分钟价格结构转换点，结合成交量和 orderflow 择时进出，快速捕捉盘中动量。",
        "is_builtin": True,
        "is_active": True,
        "tags": ["intraday", "volume", "gap"],
        "default_params": {
            "timeframe": "5m",
            "volume_multiplier": 1.6,
            "risk_per_trade": 0.02,
            "target_universe": "US_LARGE_MID_TECH",
        },
        "signal_sources": {"volume": "volume_spike", "structure": "break_swing"},
        "risk_profile": {"max_drawdown": 0.05, "volatility_limit": 0.22},
    },
    {
        "name": "量化动量轮动",
        "style": "量化",
        "description": "基于 30-60 天的动量/相对强度因子，结合基本面和情绪评分自动轮动标的池，适合趋势延续。",
        "is_builtin": True,
        "is_active": True,
        "tags": ["quant", "momentum", "rotation"],
        "default_params": {
            "lookback_days": 60,
            "momentum_threshold": 0.7,
            "allocation_per_leg": 0.2,
            "position_cap": 5,
        },
        "signal_sources": {"momentum": "relative_strength", "fundamental": "eps_revisions"},
        "risk_profile": {"max_drawdown": 0.1, "beta_limit": 1.2},
    },
]


async def seed_builtin_strategies(session: AsyncSession, strategies: Sequence[dict]) -> None:
    existing = await session.execute(select(Strategy).where(Strategy.is_builtin.is_(True)))
    if existing.scalars().first():
        return

    now = datetime.utcnow()
    for entry in strategies:
        strategy = Strategy(
            id=str(uuid4()),
            owner_id="system",
            version=1,
            name=entry["name"],
            style=entry["style"],
            description=entry["description"],
            is_builtin=entry["is_builtin"],
            is_active=entry["is_active"],
            tags=entry["tags"],
            default_params=entry["default_params"],
            signal_sources=entry["signal_sources"],
            risk_profile=entry["risk_profile"],
            created_at=now,
            updated_at=now,
        )
        session.add(strategy)
    await session.commit()


async def init_database():
    """初始化数据库，创建所有表"""
    print(f"正在初始化数据库 ({settings.DB_TYPE})...")
    print(f"连接地址: {settings.DATABASE_URL.split('@')[-1]}")  # 隐藏密码

    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        await seed_builtin_strategies(session, DEFAULT_BUILTIN_STRATEGIES)

    await engine.dispose()

    print("✅ 数据库初始化完成！")
    print("已创建/验证所有表结构并填充内置策略。")


if __name__ == "__main__":
    asyncio.run(init_database())
