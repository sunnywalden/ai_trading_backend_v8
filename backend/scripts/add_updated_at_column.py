"""
简单的迁移脚本:仅添加 updated_at 列到 ai_evaluation_history 表
"""
import asyncio
import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

async def add_updated_at_column():
    from app.models.db import engine
    from sqlalchemy import text
    
    async with engine.begin() as conn:
        try:
            print("检查 ai_evaluation_history 表结构...")
            
            # 检查列是否已存在
            check_sql = text("""
            SELECT COUNT(*) as count
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'ai_evaluation_history' 
            AND COLUMN_NAME = 'updated_at'
            """)
            result = await conn.execute(check_sql)
            row = result.fetchone()
            
            if row and row[0] > 0:
                print("✓ updated_at 列已存在，无需添加")
                return
            
            print("添加 updated_at 列...")
            
            # 添加 updated_at 列
            add_column_sql = text("""
            ALTER TABLE ai_evaluation_history 
            ADD COLUMN updated_at DATETIME 
            DEFAULT CURRENT_TIMESTAMP 
            ON UPDATE CURRENT_TIMESTAMP 
            COMMENT '更新时间' 
            AFTER created_at
            """)
            
            await conn.execute(add_column_sql)
            
            print("✓ 成功添加 updated_at 列")
            
        except Exception as e:
            print(f"✗ 添加失败: {e}")
            raise

if __name__ == "__main__":
    asyncio.run(add_updated_at_column())

