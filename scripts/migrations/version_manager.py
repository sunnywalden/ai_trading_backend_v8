"""
数据库版本管理工具

功能：
1. 创建版本管理表 schema_versions
2. 记录升级历史
3. 查询当前版本
4. 防止重复升级

使用方法：
    # 查询当前版本
    python scripts/migrations/version_manager.py --current
    
    # 记录升级
    python scripts/migrations/version_manager.py --record v3.1.1
    
    # 查看历史
    python scripts/migrations/version_manager.py --history
"""
import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from app.models.db import engine


class VersionManager:
    """数据库版本管理器"""
    
    async def ensure_version_table(self):
        """确保版本管理表存在"""
        async with engine.begin() as conn:
            # 检查表是否存在
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = 'schema_versions'
            """))
            exists = result.scalar() > 0
            
            if not exists:
                # 创建版本表
                await conn.execute(text("""
                    CREATE TABLE schema_versions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        version VARCHAR(32) NOT NULL UNIQUE,
                        description VARCHAR(256) NULL,
                        applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        rollback_at DATETIME NULL,
                        script_name VARCHAR(128) NULL,
                        checksum VARCHAR(64) NULL,
                        status VARCHAR(16) DEFAULT 'applied',
                        notes TEXT NULL,
                        INDEX idx_version_status (status),
                        INDEX idx_version_applied (applied_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """))
                print("✅ 创建 schema_versions 表")
                
                # 插入初始版本记录 (假设从 v2.2.2 开始)
                await conn.execute(text("""
                    INSERT INTO schema_versions (version, description, status, notes)
                    VALUES ('v2.2.2', '基础版本', 'applied', '初始化版本记录')
                """))
                print("✅ 记录初始版本 v2.2.2")
    
    async def get_current_version(self) -> Optional[str]:
        """获取当前版本"""
        await self.ensure_version_table()
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT version 
                FROM schema_versions 
                WHERE status = 'applied' 
                AND rollback_at IS NULL
                ORDER BY applied_at DESC 
                LIMIT 1
            """))
            row = result.fetchone()
            return row[0] if row else None
    
    async def check_version_exists(self, version: str) -> bool:
        """检查版本是否已应用"""
        await self.ensure_version_table()
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*)
                FROM schema_versions
                WHERE version = :version
                AND status = 'applied'
                AND rollback_at IS NULL
            """), {"version": version})
            return result.scalar() > 0
    
    async def record_upgrade(self, version: str, description: str = None, script_name: str = None):
        """记录升级"""
        await self.ensure_version_table()
        
        if await self.check_version_exists(version):
            print(f"⚠️  版本 {version} 已存在")
            return False
        
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO schema_versions (version, description, script_name, status)
                VALUES (:version, :description, :script_name, 'applied')
            """), {
                "version": version,
                "description": description or f"升级到 {version}",
                "script_name": script_name
            })
            print(f"✅ 记录版本 {version}")
            return True
    
    async def record_rollback(self, version: str):
        """记录回滚"""
        await self.ensure_version_table()
        
        async with engine.begin() as conn:
            await conn.execute(text("""
                UPDATE schema_versions
                SET rollback_at = NOW(), status = 'rolled_back'
                WHERE version = :version
            """), {"version": version})
            print(f"✅ 记录回滚 {version}")
    
    async def get_history(self) -> List[Dict]:
        """获取升级历史"""
        await self.ensure_version_table()
        
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT version, description, applied_at, rollback_at, status, script_name
                FROM schema_versions
                ORDER BY applied_at DESC
            """))
            rows = result.fetchall()
            
            history = []
            for row in rows:
                history.append({
                    "version": row[0],
                    "description": row[1],
                    "applied_at": row[2],
                    "rollback_at": row[3],
                    "status": row[4],
                    "script_name": row[5]
                })
            return history
    
    async def display_current(self):
        """显示当前版本"""
        version = await self.get_current_version()
        print("\n" + "="*60)
        print("📌 当前数据库版本")
        print("="*60)
        if version:
            print(f"版本: {version}")
        else:
            print("未检测到版本信息")
    
    async def display_history(self):
        """显示历史记录"""
        history = await self.get_history()
        
        print("\n" + "="*60)
        print("📜 数据库升级历史")
        print("="*60)
        
        if not history:
            print("暂无历史记录")
            return
        
        for record in history:
            status_emoji = "✅" if record["status"] == "applied" else "🔄"
            print(f"\n{status_emoji} {record['version']}")
            print(f"   描述: {record['description']}")
            print(f"   应用时间: {record['applied_at']}")
            if record['rollback_at']:
                print(f"   回滚时间: {record['rollback_at']}")
            if record['script_name']:
                print(f"   脚本: {record['script_name']}")
            print(f"   状态: {record['status']}")


async def main():
    parser = argparse.ArgumentParser(description="数据库版本管理")
    parser.add_argument("--current", action="store_true", help="显示当前版本")
    parser.add_argument("--history", action="store_true", help="显示历史记录")
    parser.add_argument("--record", type=str, help="记录新版本")
    parser.add_argument("--description", type=str, help="版本描述")
    parser.add_argument("--script", type=str, help="脚本名称")
    parser.add_argument("--rollback", type=str, help="记录回滚版本")
    parser.add_argument("--init", action="store_true", help="初始化版本表")
    
    args = parser.parse_args()
    manager = VersionManager()
    
    try:
        if args.init:
            await manager.ensure_version_table()
            print("✅ 版本管理表初始化完成")
        elif args.current:
            await manager.display_current()
        elif args.history:
            await manager.display_history()
        elif args.record:
            success = await manager.record_upgrade(
                args.record, 
                args.description,
                args.script
            )
            sys.exit(0 if success else 1)
        elif args.rollback:
            await manager.record_rollback(args.rollback)
        else:
            parser.print_help()
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
