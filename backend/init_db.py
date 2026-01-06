"""
数据库初始化脚本

创建所有必需的数据库表
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.db import Base
from app.models.symbol_behavior_stats import SymbolBehaviorStats
from app.models.symbol_risk_profile import SymbolRiskProfile
from app.models.macro_risk import MacroRiskScore, MacroIndicator, GeopoliticalEvent
from app.models.technical_indicator import TechnicalIndicator
from app.models.fundamental_data import FundamentalData
from app.models.position_score import PositionScore
from app.models.position_trend_snapshot import PositionTrendSnapshot
from app.models.opportunity_scan import OpportunityScanRun, OpportunityScanItem
from app.models.symbol_profile_cache import SymbolProfileCache

DATABASE_URL = "sqlite+aiosqlite:///./demo.db"


async def init_database():
    """初始化数据库，创建所有表"""
    print("正在初始化数据库...")
    
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    
    print("✅ 数据库初始化完成！")
    print(f"数据库文件：./demo.db")
    print("已创建的表：")
    print("  - symbol_behavior_stats")
    print("  - symbol_risk_profile")
    print("  - position_trend_snapshots")


if __name__ == "__main__":
    asyncio.run(init_database())
