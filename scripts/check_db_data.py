"""
检查数据库中 ai_evaluation_history 表的内容
"""
import asyncio
import sys
import os

# 将项目根目录添加到 sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

async def check_data():
    from app.models.db import engine
    from sqlalchemy import text
    
    async with engine.connect() as conn:
        try:
            print("--- 检查 ai_evaluation_history 数据 ---")
            
            # 1. 统计总数
            count_sql = text("SELECT COUNT(*) FROM ai_evaluation_history")
            result = await conn.execute(count_sql)
            total = result.scalar()
            print(f"总记录数: {total}")
            
            # 2. 列出最近 5 条
            list_sql = text("""
            SELECT id, account_id, symbol, created_at, updated_at 
            FROM ai_evaluation_history 
            ORDER BY created_at DESC 
            LIMIT 5
            """)
            result = await conn.execute(list_sql)
            rows = result.fetchall()
            
            print("\n最近记录:")
            for row in rows:
                print(f"ID: {row[0]}, Account: {row[1]}, Symbol: {row[2]}, Created: {row[3]}, Updated: {row[4]}")
                
            # 3. 检查特定账户的记录
            # 从日志中看到 account_id 是 '21272246230273657'
            acc_id = '21272246230273657'
            acc_sql = text(f"SELECT COUNT(*) FROM ai_evaluation_history WHERE account_id = '{acc_id}'")
            result = await conn.execute(acc_sql)
            acc_total = result.scalar()
            print(f"\n账户 {acc_id} 的记录数: {acc_total}")

            print("--- 检查结束 ---")
            
        except Exception as e:
            print(f"✗ 检查失败: {e}")
            raise

if __name__ == "__main__":
    asyncio.run(check_data())
