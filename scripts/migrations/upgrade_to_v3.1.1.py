"""
数据库升级脚本：从 v2.2.2 升级到 v3.1.1

主要变更：
1. 为 strategy_run_assets 表添加 action 和 direction 字段
2. 创建 strategy_notifications 表
3. 创建 signal_performance 表
4. 为 trading_signals 表添加 strategy_id 字段
5. 添加必要的索引

使用方法：
    python scripts/migrations/upgrade_to_v3.1.1.py [--production]
    
选项：
    --production: 生产环境模式，会要求确认并创建备份
"""
import asyncio
import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.models.db import engine
from app.core.config import settings


class DatabaseUpgrader:
    """数据库升级器"""
    
    def __init__(self, production: bool = False):
        self.production = production
        self.changes_made = []
        self.errors = []
        
    async def confirm_production(self):
        """生产环境确认"""
        if not self.production:
            return True
            
        print("\n" + "="*60)
        print("⚠️  生产环境升级警告")
        print("="*60)
        print(f"数据库: {settings.DATABASE_URL}")
        print(f"时间: {datetime.now()}")
        print("\n升级前请确认：")
        print("1. ✅ 已完整备份数据库")
        print("2. ✅ 在测试环境验证过升级流程")
        print("3. ✅ 已通知相关人员")
        print("4. ✅ 在维护窗口执行")
        print("="*60)
        
        response = input("\n输入 'YES' 继续升级，其他任意键取消: ")
        return response == "YES"
    
    async def check_version(self):
        """检查当前版本"""
        print("\n📋 检查数据库版本...")
        
        async with engine.begin() as conn:
            # 检查是否存在 strategy_notifications 表（v3.1.1 新增）
            result = await conn.execute(text("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE() 
                AND table_name = 'strategy_notifications'
            """))
            exists = result.scalar() > 0
            
            if exists:
                print("❌ 数据库已经是 v3.1.1 版本，无需升级")
                return False
                
            print("✅ 检测到 v2.2.2 版本，可以升级")
            return True
    
    async def add_strategy_run_assets_columns(self):
        """为 strategy_run_assets 添加 action 和 direction 字段"""
        print("\n📝 升级 strategy_run_assets 表...")
        
        async with engine.begin() as conn:
            # 检查 action 列是否存在
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'strategy_run_assets'
                AND column_name = 'action'
            """))
            action_exists = result.scalar() > 0
            
            if not action_exists:
                await conn.execute(text("""
                    ALTER TABLE strategy_run_assets 
                    ADD COLUMN action VARCHAR(16) NULL AFTER weight
                """))
                self.changes_made.append("✅ 添加 strategy_run_assets.action 列")
                print("  ✅ 添加 action 列")
            else:
                print("  ℹ️  action 列已存在，跳过")
            
            # 检查 direction 列是否存在
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'strategy_run_assets'
                AND column_name = 'direction'
            """))
            direction_exists = result.scalar() > 0
            
            if not direction_exists:
                await conn.execute(text("""
                    ALTER TABLE strategy_run_assets 
                    ADD COLUMN direction VARCHAR(16) NULL AFTER action
                """))
                self.changes_made.append("✅ 添加 strategy_run_assets.direction 列")
                print("  ✅ 添加 direction 列")
            else:
                print("  ℹ️  direction 列已存在，跳过")
    
    async def create_strategy_notifications_table(self):
        """创建 strategy_notifications 表"""
        print("\n📝 创建 strategy_notifications 表...")
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = 'strategy_notifications'
            """))
            exists = result.scalar() > 0
            
            if not exists:
                await conn.execute(text("""
                    CREATE TABLE strategy_notifications (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        run_id VARCHAR(64) NOT NULL,
                        channel VARCHAR(32) NOT NULL,
                        title VARCHAR(256) NULL,
                        content TEXT NULL,
                        status VARCHAR(16) DEFAULT 'pending',
                        error_message TEXT NULL,
                        sent_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_notif_run (run_id),
                        INDEX idx_notif_status (status),
                        INDEX idx_notif_created (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """))
                self.changes_made.append("✅ 创建 strategy_notifications 表")
                print("  ✅ 表创建成功")
            else:
                print("  ℹ️  表已存在，跳过")
    
    async def create_signal_performance_table(self):
        """创建 signal_performance 表"""
        print("\n📝 创建 signal_performance 表...")
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = 'signal_performance'
            """))
            exists = result.scalar() > 0
            
            if not exists:
                await conn.execute(text("""
                    CREATE TABLE signal_performance (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        signal_id VARCHAR(64) NOT NULL UNIQUE,
                        symbol VARCHAR(32) NOT NULL,
                        strategy_id VARCHAR(64) NULL,
                        entry_price DECIMAL(10,2) NULL,
                        exit_price DECIMAL(10,2) NULL,
                        pnl DECIMAL(10,2) NULL,
                        pnl_pct DECIMAL(5,2) NULL,
                        holding_period_hours INT NULL,
                        win BOOLEAN NULL,
                        closed_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_perf_signal (signal_id),
                        INDEX idx_perf_strategy (strategy_id),
                        INDEX idx_perf_symbol (symbol),
                        INDEX idx_perf_closed (closed_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """))
                self.changes_made.append("✅ 创建 signal_performance 表")
                print("  ✅ 表创建成功")
            else:
                print("  ℹ️  表已存在，跳过")
    
    async def add_trading_signals_strategy_id(self):
        """为 trading_signals 表添加 strategy_id 字段"""
        print("\n📝 升级 trading_signals 表...")
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'trading_signals'
                AND column_name = 'strategy_id'
            """))
            exists = result.scalar() > 0
            
            if not exists:
                await conn.execute(text("""
                    ALTER TABLE trading_signals 
                    ADD COLUMN strategy_id VARCHAR(64) NULL AFTER id
                """))
                
                # 添加索引
                await conn.execute(text("""
                    ALTER TABLE trading_signals 
                    ADD INDEX idx_signal_strategy (strategy_id)
                """))
                
                self.changes_made.append("✅ 添加 trading_signals.strategy_id 列和索引")
                print("  ✅ 添加 strategy_id 列和索引")
            else:
                print("  ℹ️  strategy_id 列已存在，跳过")
    
    async def add_indexes(self):
        """添加优化索引"""
        print("\n📝 添加优化索引...")
        
        indexes = [
            ("strategies", "idx_strategy_active", "is_active"),
            ("strategy_runs", "idx_run_started", "started_at"),
            ("strategy_run_assets", "idx_asset_symbol", "symbol"),
        ]
        
        async with engine.begin() as conn:
            for table, index_name, column in indexes:
                # 检查索引是否存在
                result = await conn.execute(text(f"""
                    SELECT COUNT(*)
                    FROM information_schema.statistics
                    WHERE table_schema = DATABASE()
                    AND table_name = '{table}'
                    AND index_name = '{index_name}'
                """))
                exists = result.scalar() > 0
                
                if not exists:
                    try:
                        await conn.execute(text(f"""
                            ALTER TABLE {table} 
                            ADD INDEX {index_name} ({column})
                        """))
                        print(f"  ✅ 添加索引 {table}.{index_name}")
                        self.changes_made.append(f"✅ 添加索引 {table}.{index_name}")
                    except Exception as e:
                        print(f"  ℹ️  索引 {index_name} 可能已存在: {e}")
                else:
                    print(f"  ℹ️  索引 {table}.{index_name} 已存在，跳过")
    
    async def run(self):
        """执行升级"""
        try:
            print("\n" + "="*60)
            print("🚀 数据库升级：v2.2.2 → v3.1.1")
            print("="*60)
            
            # 生产环境确认
            if not await self.confirm_production():
                print("\n❌ 升级已取消")
                return False
            
            # 检查版本
            if not await self.check_version():
                return False
            
            # 执行升级步骤
            await self.add_strategy_run_assets_columns()
            await self.create_strategy_notifications_table()
            await self.create_signal_performance_table()
            await self.add_trading_signals_strategy_id()
            await self.add_indexes()
            
            # 显示总结
            print("\n" + "="*60)
            print("✅ 升级完成！")
            print("="*60)
            print(f"\n总计执行了 {len(self.changes_made)} 项变更：")
            for change in self.changes_made:
                print(f"  {change}")
            
            print("\n📋 后续步骤：")
            print("  1. 运行验证脚本: python scripts/migrations/verify_v3.1.1.py")
            print("  2. 初始化新策略: python scripts/bootstrap/init_strategies.py")
            print("  3. 重启应用服务")
            print("  4. 监控应用日志")
            
            return True
            
        except Exception as e:
            print(f"\n❌ 升级失败: {e}")
            import traceback
            traceback.print_exc()
            
            print("\n🔄 建议回滚操作：")
            print("  mysql -u root -p ai_trading < backup_before_v3.1.1.sql")
            return False


async def main():
    parser = argparse.ArgumentParser(description="升级数据库到 v3.1.1")
    parser.add_argument(
        "--production",
        action="store_true",
        help="生产环境模式（需要确认）"
    )
    args = parser.parse_args()
    
    upgrader = DatabaseUpgrader(production=args.production)
    success = await upgrader.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
