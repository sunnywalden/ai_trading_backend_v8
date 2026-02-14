"""
数据库验证脚本：验证 v3.1.1 版本的数据库结构

检查项：
1. 表是否存在
2. 字段是否存在及类型正确
3. 索引是否存在
4. 数据完整性

使用方法：
    python scripts/migrations/verify_v3.1.1.py
"""
import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.models.db import engine


class DatabaseVerifier:
    """数据库验证器"""
    
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
    
    async def check_table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        async with engine.begin() as conn:
            result = await conn.execute(text(f"""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = '{table_name}'
            """))
            return result.scalar() > 0
    
    async def check_column_exists(self, table: str, column: str, expected_type: str = None) -> bool:
        """检查列是否存在及类型"""
        async with engine.begin() as conn:
            result = await conn.execute(text(f"""
                SELECT column_type
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = '{table}'
                AND column_name = '{column}'
            """))
            row = result.fetchone()
            
            if not row:
                return False
            
            if expected_type:
                actual_type = row[0].lower()
                # 简单的类型匹配
                if expected_type.lower() not in actual_type:
                    self.warnings.append(f"⚠️  {table}.{column} 类型不匹配: 期望 {expected_type}, 实际 {actual_type}")
            
            return True
    
    async def check_index_exists(self, table: str, index_name: str) -> bool:
        """检查索引是否存在"""
        async with engine.begin() as conn:
            result = await conn.execute(text(f"""
                SELECT COUNT(*)
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                AND table_name = '{table}'
                AND index_name = '{index_name}'
            """))
            return result.scalar() > 0
    
    async def verify_core_tables(self):
        """验证核心表"""
        print("\n📋 验证核心表...")
        
        required_tables = [
            "strategies",
            "strategy_runs",
            "strategy_run_assets",
            "strategy_run_logs",
            "strategy_notifications",  # v3.1.1 新增
            "signal_performance",      # v3.1.1 新增
            "trading_signals",
            "symbol_behavior_stats",
        ]
        
        for table in required_tables:
            exists = await self.check_table_exists(table)
            if exists:
                self.passed.append(f"✅ 表 {table} 存在")
                print(f"  ✅ {table}")
            else:
                self.failed.append(f"❌ 表 {table} 不存在")
                print(f"  ❌ {table} 不存在")
    
    async def verify_v311_columns(self):
        """验证 v3.1.1 新增的列"""
        print("\n📋 验证 v3.1.1 新增列...")
        
        checks = [
            ("strategy_run_assets", "action", "varchar"),
            ("strategy_run_assets", "direction", "varchar"),
            ("trading_signals", "strategy_id", "varchar"),
        ]
        
        for table, column, expected_type in checks:
            exists = await self.check_column_exists(table, column, expected_type)
            if exists:
                self.passed.append(f"✅ {table}.{column} 存在")
                print(f"  ✅ {table}.{column}")
            else:
                self.failed.append(f"❌ {table}.{column} 不存在")
                print(f"  ❌ {table}.{column} 不存在")
    
    async def verify_strategy_notifications_structure(self):
        """验证 strategy_notifications 表结构"""
        print("\n📋 验证 strategy_notifications 表结构...")
        
        if not await self.check_table_exists("strategy_notifications"):
            self.failed.append("❌ strategy_notifications 表不存在")
            print("  ❌ 表不存在，跳过结构检查")
            return
        
        required_columns = [
            ("id", "int"),
            ("run_id", "varchar"),
            ("channel", "varchar"),
            ("title", "varchar"),
            ("content", "text"),
            ("status", "varchar"),
            ("sent_at", "datetime"),
            ("created_at", "datetime"),
        ]
        
        for column, expected_type in required_columns:
            exists = await self.check_column_exists("strategy_notifications", column, expected_type)
            if exists:
                print(f"  ✅ {column}")
            else:
                self.failed.append(f"❌ strategy_notifications.{column} 不存在")
                print(f"  ❌ {column} 不存在")
    
    async def verify_signal_performance_structure(self):
        """验证 signal_performance 表结构"""
        print("\n📋 验证 signal_performance 表结构...")
        
        if not await self.check_table_exists("signal_performance"):
            self.failed.append("❌ signal_performance 表不存在")
            print("  ❌ 表不存在，跳过结构检查")
            return
        
        required_columns = [
            ("id", "int"),
            ("signal_id", "varchar"),
            ("symbol", "varchar"),
            ("strategy_id", "varchar"),
            ("entry_price", "decimal"),
            ("exit_price", "decimal"),
            ("pnl", "decimal"),
            ("pnl_pct", "decimal"),
            ("holding_period_hours", "int"),
            ("win", "tinyint"),
            ("closed_at", "datetime"),
            ("created_at", "datetime"),
        ]
        
        for column, expected_type in required_columns:
            exists = await self.check_column_exists("signal_performance", column, expected_type)
            if exists:
                print(f"  ✅ {column}")
            else:
                self.failed.append(f"❌ signal_performance.{column} 不存在")
                print(f"  ❌ {column} 不存在")
    
    async def verify_indexes(self):
        """验证关键索引"""
        print("\n📋 验证索引...")
        
        indexes = [
            ("strategy_notifications", "idx_notif_run"),
            ("strategy_notifications", "idx_notif_status"),
            ("signal_performance", "idx_perf_signal"),
            ("signal_performance", "idx_perf_strategy"),
            ("trading_signals", "idx_signal_strategy"),
        ]
        
        for table, index_name in indexes:
            exists = await self.check_index_exists(table, index_name)
            if exists:
                self.passed.append(f"✅ 索引 {table}.{index_name} 存在")
                print(f"  ✅ {table}.{index_name}")
            else:
                self.warnings.append(f"⚠️  索引 {table}.{index_name} 不存在（性能可能受影响）")
                print(f"  ⚠️  {table}.{index_name} 不存在")
    
    async def verify_data_integrity(self):
        """验证数据完整性"""
        print("\n📋 验证数据完整性...")
        
        async with engine.begin() as conn:
            # 检查策略数量
            result = await conn.execute(text("SELECT COUNT(*) FROM strategies"))
            strategy_count = result.scalar()
            print(f"  📊 策略数量: {strategy_count}")
            
            if strategy_count < 15:
                self.warnings.append(f"⚠️  策略数量不足 {strategy_count}/15，可能需要运行 init_strategies.py")
                print(f"    ⚠️  期望至少 15 个策略")
            else:
                self.passed.append(f"✅ 策略数量正常 ({strategy_count})")
            
            # 检查是否有运行记录
            result = await conn.execute(text("SELECT COUNT(*) FROM strategy_runs"))
            run_count = result.scalar()
            print(f"  📊 运行记录数: {run_count}")
            
            # 检查信号数量
            result = await conn.execute(text("SELECT COUNT(*) FROM trading_signals"))
            signal_count = result.scalar()
            print(f"  📊 交易信号数: {signal_count}")
    
    async def verify_sample_queries(self):
        """验证示例查询"""
        print("\n📋 测试示例查询...")
        
        queries = [
            ("查询前5个策略", "SELECT id, name, style FROM strategies LIMIT 5"),
            ("查询最近运行", "SELECT id, status, started_at FROM strategy_runs ORDER BY started_at DESC LIMIT 3"),
            ("查询通知记录", "SELECT id, channel, status FROM strategy_notifications LIMIT 3"),
        ]
        
        for desc, sql in queries:
            try:
                async with engine.begin() as conn:
                    result = await conn.execute(text(sql))
                    rows = result.fetchall()
                    print(f"  ✅ {desc}: {len(rows)} 条记录")
                    self.passed.append(f"✅ {desc} 成功")
            except Exception as e:
                print(f"  ❌ {desc} 失败: {e}")
                self.failed.append(f"❌ {desc} 失败: {e}")
    
    async def run(self):
        """执行验证"""
        try:
            print("\n" + "="*60)
            print("🔍 数据库验证：v3.1.1 版本")
            print("="*60)
            
            await self.verify_core_tables()
            await self.verify_v311_columns()
            await self.verify_strategy_notifications_structure()
            await self.verify_signal_performance_structure()
            await self.verify_indexes()
            await self.verify_data_integrity()
            await self.verify_sample_queries()
            
            # 显示总结
            print("\n" + "="*60)
            print("📊 验证结果")
            print("="*60)
            print(f"✅ 通过: {len(self.passed)} 项")
            print(f"⚠️  警告: {len(self.warnings)} 项")
            print(f"❌ 失败: {len(self.failed)} 项")
            
            if self.failed:
                print("\n❌ 失败项:")
                for item in self.failed:
                    print(f"  {item}")
            
            if self.warnings:
                print("\n⚠️  警告项:")
                for item in self.warnings:
                    print(f"  {item}")
            
            if not self.failed:
                print("\n🎉 数据库结构验证通过!")
                print("\n建议操作:")
                if strategy_count := len(self.warnings):
                    print("  1. 检查警告项")
                print("  2. 运行应用测试")
                print("  3. 监控应用日志")
                return True
            else:
                print("\n❌ 数据库结构验证失败，请检查上述失败项")
                print("\n可能的解决方案:")
                print("  1. 重新运行升级脚本: python scripts/migrations/upgrade_to_v3.1.1.py")
                print("  2. 检查数据库连接配置")
                print("  3. 查看详细的错误信息")
                return False
                
        except Exception as e:
            print(f"\n❌ 验证过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False


async def main():
    verifier = DatabaseVerifier()
    success = await verifier.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
