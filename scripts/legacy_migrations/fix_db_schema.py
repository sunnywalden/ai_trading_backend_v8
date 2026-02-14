"""
修复脚本：彻底移除 batch_id 并同步数据库结构
"""
import asyncio
import sys
import os

# 将项目根目录添加到 sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

async def fix_database_schema():
    from app.models.db import engine
    from sqlalchemy import text
    
    async with engine.begin() as conn:
        try:
            print("--- 开始修复 ai_evaluation_history 表结构 ---")
            
            # 1. 检查列是否存在
            columns_query = text("SHOW COLUMNS FROM ai_evaluation_history")
            result = await conn.execute(columns_query)
            columns = [row[0] for row in result.fetchall()]
            
            print(f"当前列: {', '.join(columns)}")
            
            # 2. 如果存在 batch_id，则删除
            if 'batch_id' in columns:
                print("删除 batch_id 列...")
                # 先尝试删除可能存在的索引
                try:
                    await conn.execute(text("ALTER TABLE ai_evaluation_history DROP INDEX idx_eval_account_batch"))
                    print("✓ 已删除索引 idx_eval_account_batch")
                except Exception:
                    print("ℹ 索引 idx_eval_account_batch 不存在或已删除")

                await conn.execute(text("ALTER TABLE ai_evaluation_history DROP COLUMN batch_id"))
                print("✓ 成功删除 batch_id 列")
            else:
                print("✓ batch_id 列已不存在")

            # 3. 检查并添加唯一约束
            indexes_query = text("SHOW INDEX FROM ai_evaluation_history")
            result = await conn.execute(indexes_query)
            indexes = [row[2] for row in result.fetchall()]
            
            if 'uk_account_symbol' not in indexes:
                print("添加唯一约束 uk_account_symbol (account_id, symbol)...")
                # 清理重复数据（保留最新的 id）
                cleanup_sql = """
                DELETE FROM ai_evaluation_history 
                WHERE id NOT IN (
                    SELECT id FROM (
                        SELECT MAX(id) as id 
                        FROM ai_evaluation_history 
                        GROUP BY account_id, symbol
                    ) tmp
                )
                """
                await conn.execute(text(cleanup_sql))
                await conn.execute(text("ALTER TABLE ai_evaluation_history ADD UNIQUE KEY uk_account_symbol (account_id, symbol)"))
                print("✓ 成功添加唯一约束")
            else:
                print("✓ 唯一约束 uk_account_symbol 已存在")

            print("\n--- 开始检查 trading_signals 表结构 ---")
            
            # 4. 检查 trading_signals 表
            columns_query = text("SHOW COLUMNS FROM trading_signals")
            result = await conn.execute(columns_query)
            ts_columns = [row[0] for row in result.fetchall()]
            
            print(f"trading_signals 当前列: {', '.join(ts_columns)}")
            
            # 检查 pnl_pct
            if 'pnl_pct' not in ts_columns:
                print("未发现 pnl_pct 列，正在添加...")
                await conn.execute(text("ALTER TABLE trading_signals ADD COLUMN pnl_pct FLOAT NULL COMMENT '盈亏百分比'"))
                print("✓ 成功添加 pnl_pct 列")
            else:
                print("✓ pnl_pct 列已存在")
                
            # 检查 pnl
            if 'pnl' not in ts_columns:
                print("未发现 pnl 列，正在添加...")
                await conn.execute(text("ALTER TABLE trading_signals ADD COLUMN pnl FLOAT NULL COMMENT '盈亏（绝对金额）'"))
                print("✓ 成功添加 pnl 列")
            else:
                print("✓ pnl 列已存在")

            # 检查 is_winner
            if 'is_winner' not in ts_columns:
                print("未发现 is_winner 列，正在添加...")
                await conn.execute(text("ALTER TABLE trading_signals ADD COLUMN is_winner VARCHAR(8) NULL COMMENT 'YES/NO - 是否盈利交易'"))
                print("✓ 成功添加 is_winner 列")
            else:
                print("✓ is_winner 列已存在")

            print("--- 修复完成 ---")
            
        except Exception as e:
            print(f"✗ 修复失败: {e}")
            raise

if __name__ == "__main__":
    asyncio.run(fix_database_schema())
