"""
数据库初始化脚本

创建所有必需的数据库表
"""
import asyncio
from app.core.config import settings
from app.models.db import Base, engine
from app.models.symbol_behavior_stats import SymbolBehaviorStats
from app.models.symbol_risk_profile import SymbolRiskProfile
from app.models.macro_risk import MacroRiskScore, MacroIndicator, GeopoliticalEvent
from app.models.technical_indicator import TechnicalIndicator
from app.models.fundamental_data import FundamentalData
from app.models.position_score import PositionScore
from app.models.position_trend_snapshot import PositionTrendSnapshot
from app.models.opportunity_scan import OpportunityScanRun, OpportunityScanItem
from app.models.symbol_profile_cache import SymbolProfileCache

async def init_database():
    """初始化数据库，创建所有表"""
    print(f"正在初始化数据库 ({settings.DB_TYPE})...")
    print(f"连接地址: {settings.DATABASE_URL.split('@')[-1]}") # 隐藏密码
    
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    
    print("✅ 数据库初始化完成！")
    print("已创建/验证所有表结构。")


if __name__ == "__main__":
    asyncio.run(init_database())
