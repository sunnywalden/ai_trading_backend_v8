import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.core.config import settings

async def verify():
    print("🔍 验证 v3.2.1 数据库结构...")
    engine = create_async_engine(settings.DATABASE_URL)
    
    async def get_inspection(conn):
        from sqlalchemy import inspect
        return inspect(conn)

    async with engine.connect() as conn:
        # 使用 SQLAlchemy Inspector 进行跨数据库验证
        from sqlalchemy import inspect
        
        def check_structure(sync_conn):
            inspector = inspect(sync_conn)
            tables = inspector.get_table_names()
            
            # 验证表
            if 'user_preferences' in tables:
                print("  ✅ 表 'user_preferences' 已存在")
            else:
                print("  ❌ 表 'user_preferences' 缺失！")

            # 验证字段
            columns = [c['name'] for c in inspector.get_columns('strategies')]
            if 'priority' in columns:
                print("  ✅ 字段 'priority' 已存在于 'strategies' 表")
            else:
                print("  ❌ 字段 'priority' 在 'strategies' 表中缺失！")

        await conn.run_sync(check_structure)

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(verify())
