"""
持仓评估和宏观风险分析模块的数据库表结构初始化脚本
"""
import asyncio
from app.core.config import settings
from app.models.db import Base, engine

# 导入所有模型以确保它们被注册到 Base.metadata
from app.models.position_score import PositionScore
from app.models.technical_indicator import TechnicalIndicator
from app.models.fundamental_data import FundamentalData
from app.models.macro_risk import MacroRiskScore, MacroIndicator, GeopoliticalEvent
from app.models.position_trend_snapshot import PositionTrendSnapshot
from app.models.symbol_behavior_stats import SymbolBehaviorStats
from app.models.symbol_risk_profile import SymbolRiskProfile
from app.models.symbol_profile_cache import SymbolProfileCache


async def create_tables():
    print(f"正在通过 SQLAlchemy 创建表结构 ({settings.DB_TYPE})...")
    async with engine.begin() as conn:
        # 使用 SQLAlchemy 自动创建表
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    print("✅ 表结构创建/验证完成！")


if __name__ == "__main__":
    asyncio.run(create_tables())
