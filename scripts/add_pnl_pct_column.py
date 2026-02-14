"""
修复脚本：检查并添加 trading_signals 表缺失的 pnl_pct 和 pnl 列
"""
import asyncio
import sys
import os

# 将项目根目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def fix_trading_signals_schema():
    from app.models.db import engine
    from sqlalchemy import text
    
    print(f"Connecting to database using engine: {engine.url}")
    
    async with engine.begin() as conn:
        try:
            print("--- 开始检查 trading_signals 表结构 ---")
            
            # 1. 获取当前列
            columns_query = text("SHOW COLUMNS FROM trading_signals")
            result = await conn.execute(columns_query)
            columns = [row[0] for row in result.fetchall()]
            
            print(f"当前列: {', '.join(columns)}")
            
            # 2. 检查 pnl_pct
            if 'pnl_pct' not in columns:
                print("未发现 pnl_pct 列，正在添加...")
                await conn.execute(text("ALTER TABLE trading_signals ADD COLUMN pnl_pct FLOAT NULL COMMENT '盈亏百分比'"))
                print("✓ 成功添加 pnl_pct 列")
            else:
                print("✓ pnl_pct 列已存在")
                
            # 3. 检查 pnl (顺便检查)
            if 'pnl' not in columns:
                print("未发现 pnl 列，正在添加...")
                await conn.execute(text("ALTER TABLE trading_signals ADD COLUMN pnl FLOAT NULL COMMENT '盈亏（绝对金额）'"))
                print("✓ 成功添加 pnl 列")
            else:
                print("✓ pnl 列已存在")
                
            print("--- 修复完成 ---")
            
        except Exception as e:
            print(f"✗ 修复失败: {e}")
            raise

if __name__ == "__main__":
    try:
        asyncio.run(fix_trading_signals_schema())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error executing script: {e}")
