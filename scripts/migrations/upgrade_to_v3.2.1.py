import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# 确保可以导入后端配置
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.core.config import settings

async def upgrade():
    print("🚀 开始升级数据库到 v3.2.1...")
    engine = create_async_engine(settings.DATABASE_URL)
    
    async with engine.begin() as conn:
        # 1. 创建用户偏好表
        print("  - 检查并创建 user_preferences 表...")
        # 注意：MySQL 使用 AUTO_INCREMENT，SQLite 使用 AUTOINCREMENT
        auto_inc = "AUTO_INCREMENT" if "mysql" in settings.DATABASE_URL else "AUTOINCREMENT"
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY {auto_inc},
                user_id VARCHAR(50) NOT NULL UNIQUE,
                theme VARCHAR(20) DEFAULT 'dark',
                language VARCHAR(10) DEFAULT 'zh-CN',
                notifications_enabled BOOLEAN DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """))

        # 2. 为 strategies 添加 priority 字段
        print("  - 为 strategies 表添加 priority 字段...")
        try:
            # SQLite 语法：添加列
            await conn.execute(text("ALTER TABLE strategies ADD COLUMN priority INTEGER DEFAULT 0"))
            print("    ✅ 字段添加成功")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                print("    ℹ️  字段 priority 已存在，跳过")
            else:
                print(f"    ❌ 错误: {e}")

    print("✅ 数据库升级完成。")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(upgrade())
