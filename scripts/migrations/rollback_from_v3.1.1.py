"""
数据库回滚脚本：从 v3.1.1 回滚到 v2.2.2

⚠️ 警告：此脚本会删除 v3.1.1 新增的表和列，可能导致数据丢失！

回滚操作：
1. 删除 strategy_notifications 表（及其数据）
2. 删除 signal_performance 表（及其数据）
3. 删除 strategy_run_assets.action 和 direction 列
4. 删除 trading_signals.strategy_id 列

使用方法：
    python scripts/migrations/rollback_from_v3.1.1.py [--confirm]
    
选项：
    --confirm: 确认执行回滚（必需）
"""
import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.models.db import engine
from app.core.config import settings


class DatabaseRollback:
    """数据库回滚器"""
    
    def __init__(self):
        self.changes_made = []
        self.errors = []
    
    async def confirm_rollback(self):
        """确认回滚操作"""
        print("\n" + "="*60)
        print("⚠️⚠️⚠️  数据库回滚警告  ⚠️⚠️⚠️")
        print("="*60)
        print(f"数据库: {settings.DATABASE_URL}")
        print(f"时间: {datetime.now()}")
        print("\n此操作将：")
        print("  ❌ 删除 strategy_notifications 表及所有数据")
        print("  ❌ 删除 signal_performance 表及所有数据")
        print("  ❌ 删除 strategy_run_assets 的 action 和 direction 列")
        print("  ❌ 删除 trading_signals 的 strategy_id 列")
        print("\n⚠️  这些数据将无法恢复！")
        print("="*60)
        print("\n回滚前请确认：")
        print("  1. ✅ 已备份数据库")
        print("  2. ✅ 了解数据丢失风险")
        print("  3. ✅ 已通知相关人员")
        print("="*60)
        
        response = input("\n输入 'ROLLBACK' 继续，其他任意键取消: ")
        return response == "ROLLBACK"
    
    async def backup_v311_data(self):
        """备份 v3.1.1 数据（可选）"""
        print("\n💾 备份 v3.1.1 数据...")
        
        try:
            async with engine.begin() as conn:
                # 统计即将删除的数据
                result = await conn.execute(text("SELECT COUNT(*) FROM strategy_notifications"))
                notif_count = result.scalar()
                
                result = await conn.execute(text("SELECT COUNT(*) FROM signal_performance"))
                perf_count = result.scalar()
                
                result = await conn.execute(text("""
                    SELECT COUNT(*) 
                    FROM strategy_run_assets 
                    WHERE action IS NOT NULL OR direction IS NOT NULL
                """))
                asset_count = result.scalar()
                
                result = await conn.execute(text("""
                    SELECT COUNT(*) 
                    FROM trading_signals 
                    WHERE strategy_id IS NOT NULL
                """))
                signal_count = result.scalar()
                
                print(f"  📊 strategy_notifications: {notif_count} 条记录将被删除")
                print(f"  📊 signal_performance: {perf_count} 条记录将被删除")
                print(f"  📊 strategy_run_assets: {asset_count} 条记录包含 action/direction")
                print(f"  📊 trading_signals: {signal_count} 条记录包含 strategy_id")
                
                total = notif_count + perf_count
                if total > 0:
                    print(f"\n  ⚠️  总计 {total} 条记录将被删除")
                    print("  💡 建议: 手动导出这些表的数据用于归档")
                
                return True
                
        except Exception as e:
            print(f"  ⚠️  备份检查失败: {e}")
            return False
    
    async def drop_strategy_notifications_table(self):
        """删除 strategy_notifications 表"""
        print("\n🗑️  删除 strategy_notifications 表...")
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = 'strategy_notifications'
            """))
            exists = result.scalar() > 0
            
            if exists:
                await conn.execute(text("DROP TABLE strategy_notifications"))
                self.changes_made.append("✅ 删除 strategy_notifications 表")
                print("  ✅ 表已删除")
            else:
                print("  ℹ️  表不存在，跳过")
    
    async def drop_signal_performance_table(self):
        """删除 signal_performance 表"""
        print("\n🗑️  删除 signal_performance 表...")
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = 'signal_performance'
            """))
            exists = result.scalar() > 0
            
            if exists:
                await conn.execute(text("DROP TABLE signal_performance"))
                self.changes_made.append("✅ 删除 signal_performance 表")
                print("  ✅ 表已删除")
            else:
                print("  ℹ️  表不存在，跳过")
    
    async def remove_strategy_run_assets_columns(self):
        """删除 strategy_run_assets 的列"""
        print("\n🗑️  删除 strategy_run_assets 列...")
        
        async with engine.begin() as conn:
            # 删除 action 列
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'strategy_run_assets'
                AND column_name = 'action'
            """))
            action_exists = result.scalar() > 0
            
            if action_exists:
                await conn.execute(text("ALTER TABLE strategy_run_assets DROP COLUMN action"))
                self.changes_made.append("✅ 删除 strategy_run_assets.action 列")
                print("  ✅ 删除 action 列")
            else:
                print("  ℹ️  action 列不存在，跳过")
            
            # 删除 direction 列
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'strategy_run_assets'
                AND column_name = 'direction'
            """))
            direction_exists = result.scalar() > 0
            
            if direction_exists:
                await conn.execute(text("ALTER TABLE strategy_run_assets DROP COLUMN direction"))
                self.changes_made.append("✅ 删除 strategy_run_assets.direction 列")
                print("  ✅ 删除 direction 列")
            else:
                print("  ℹ️  direction 列不存在，跳过")
    
    async def remove_trading_signals_strategy_id(self):
        """删除 trading_signals 的 strategy_id 列"""
        print("\n🗑️  删除 trading_signals 列...")
        
        async with engine.begin() as conn:
            # 先删除索引
            try:
                await conn.execute(text("ALTER TABLE trading_signals DROP INDEX idx_signal_strategy"))
                print("  ✅ 删除索引 idx_signal_strategy")
            except Exception as e:
                print(f"  ℹ️  索引可能不存在: {e}")
            
            # 删除 strategy_id 列
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'trading_signals'
                AND column_name = 'strategy_id'
            """))
            exists = result.scalar() > 0
            
            if exists:
                await conn.execute(text("ALTER TABLE trading_signals DROP COLUMN strategy_id"))
                self.changes_made.append("✅ 删除 trading_signals.strategy_id 列")
                print("  ✅ 删除 strategy_id 列")
            else:
                print("  ℹ️  strategy_id 列不存在，跳过")
    
    async def run(self):
        """执行回滚"""
        try:
            print("\n" + "="*60)
            print("🔄 数据库回滚：v3.1.1 → v2.2.2")
            print("="*60)
            
            # 确认回滚
            if not await self.confirm_rollback():
                print("\n❌ 回滚已取消")
                return False
            
            # 备份检查
            if not await self.backup_v311_data():
                response = input("\n⚠️  备份检查失败，是否继续？(yes/no): ")
                if response.lower() != "yes":
                    print("❌ 回滚已取消")
                    return False
            
            # 执行回滚步骤
            await self.drop_strategy_notifications_table()
            await self.drop_signal_performance_table()
            await self.remove_strategy_run_assets_columns()
            await self.remove_trading_signals_strategy_id()
            
            # 显示总结
            print("\n" + "="*60)
            print("✅ 回滚完成！")
            print("="*60)
            print(f"\n总计执行了 {len(self.changes_made)} 项变更：")
            for change in self.changes_made:
                print(f"  {change}")
            
            print("\n📋 后续步骤：")
            print("  1. 重启应用服务")
            print("  2. 验证应用功能")
            print("  3. 监控应用日志")
            print("  4. 如需恢复v3.1.1，运行 upgrade_to_v3.1.1.py")
            
            return True
            
        except Exception as e:
            print(f"\n❌ 回滚失败: {e}")
            import traceback
            traceback.print_exc()
            
            print("\n⚠️  数据库可能处于不一致状态！")
            print("建议操作：")
            print("  1. 从备份恢复数据库")
            print("  2. 联系技术支持")
            return False


async def main():
    parser = argparse.ArgumentParser(description="回滚数据库到 v2.2.2")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认执行回滚（必需）"
    )
    args = parser.parse_args()
    
    if not args.confirm:
        print("❌ 错误: 必须添加 --confirm 参数确认回滚操作")
        print("用法: python rollback_from_v3.1.1.py --confirm")
        sys.exit(1)
    
    rollback = DatabaseRollback()
    success = await rollback.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
