"""
迁移脚本：将 ai_evaluation_history 从批次模式改为唯一symbol模式

变更内容：
1. 删除 batch_id 列和 idx_eval_account_batch 索引
2. 添加 updated_at 列
3. 添加唯一约束 UNIQUE(account_id, symbol)
4. 对已有数据，每个 symbol 只保留最新的记录（基于 created_at）
"""
import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.config import settings
from sqlalchemy import create_engine, text

def migrate():
    # Construct database URL
    db_url = f"mysql+pymysql://{settings.DATABASE_USER}:{settings.DATABASE_PASSWORD}@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        print("===== 开始迁移 ai_evaluation_history 表 =====\n")
        
        # 步骤1: 删除旧数据，保留每个 (account_id, symbol) 的最新记录
        print("步骤1: 清理重复数据，每个symbol只保留最新记录...")
        try:
            # 使用子查询找出所有需要保留的 id
            cleanup_sql = """
            DELETE FROM ai_evaluation_history
            WHERE id NOT IN (
                SELECT * FROM (
                    SELECT MAX(id) as id
                    FROM ai_evaluation_history
                    GROUP BY account_id, symbol
                ) as keep_ids
            );
            """
            result = conn.execute(text(cleanup_sql))
            conn.commit()
            print(f"   ✓ 已清理重复记录，删除了 {result.rowcount} 条旧记录\n")
        except Exception as e:
            print(f"   ✗ 清理旧数据失败: {e}\n")
            return
        
        # 步骤2: 删除 batch_id 相关索引
        print("步骤2: 删除 idx_eval_account_batch 索引...")
        try:
            conn.execute(text("ALTER TABLE ai_evaluation_history DROP INDEX idx_eval_account_batch;"))
            conn.commit()
            print("   ✓ 已删除索引\n")
        except Exception as e:
            # 索引可能不存在
            print(f"   ⚠ 索引删除失败（可能不存在）: {e}\n")
        
        # 步骤3: 删除 batch_id 列
        print("步骤3: 删除 batch_id 列...")
        try:
            conn.execute(text("ALTER TABLE ai_evaluation_history DROP COLUMN batch_id;"))
            conn.commit()
            print("   ✓ 已删除 batch_id 列\n")
        except Exception as e:
            print(f"   ✗ 删除 batch_id 列失败: {e}\n")
            return
        
        # 步骤4: 添加 updated_at 列
        print("步骤4: 添加 updated_at 列...")
        try:
            conn.execute(text("""
                ALTER TABLE ai_evaluation_history 
                ADD COLUMN updated_at DATETIME 
                DEFAULT CURRENT_TIMESTAMP 
                ON UPDATE CURRENT_TIMESTAMP 
                COMMENT '更新时间' 
                AFTER created_at;
            """))
            conn.commit()
            print("   ✓ 已添加 updated_at 列\n")
        except Exception as e:
            print(f"   ✗ 添加 updated_at 列失败: {e}\n")
            return
        
        # 步骤5: 添加唯一约束
        print("步骤5: 添加 UNIQUE(account_id, symbol) 约束...")
        try:
            conn.execute(text("""
                ALTER TABLE ai_evaluation_history 
                ADD UNIQUE KEY uk_account_symbol (account_id, symbol);
            """))
            conn.commit()
            print("   ✓ 已添加唯一约束\n")
        except Exception as e:
            print(f"   ✗ 添加唯一约束失败: {e}\n")
            return
        
        print("===== 迁移完成！=====\n")
        print("新的表结构:")
        print("  - batch_id 列已删除")
        print("  - updated_at 列已添加")
        print("  - UNIQUE(account_id, symbol) 约束已生效")
        print("  - 每个标的只保留最新的评估记录")
        print("\n后续行为：再次评估同一标的时，将自动覆盖旧记录\n")

if __name__ == "__main__":
    migrate()
