# 数据库迁移开发工作流

本文档面向开发者，说明如何在日常开发中创建和管理数据库迁移。

## 📋 基本原则

1. **每个版本对应一组迁移脚本**（upgrade, verify, rollback）
2. **先测试后生产**：所有迁移必须在测试环境验证
3. **可回滚设计**：每个升级必须有对应的回滚脚本
4. **版本记录**：使用 version_manager 跟踪已应用的版本

## 🔄 开发流程

### 场景 1: 添加新表

假设你要为 v3.2.0 添加一个 `user_preferences` 表。

#### 1. 创建升级脚本

```bash
touch scripts/migrations/upgrade_to_v3.2.0.py
```

```python
"""
数据库升级脚本：从 v3.1.1 升级到 v3.2.0

主要变更：
1. 创建 user_preferences 表
"""
import asyncio
from sqlalchemy import text
from app.models.db import engine

async def upgrade():
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE user_preferences (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                preference_key VARCHAR(128) NOT NULL,
                preference_value TEXT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_user_pref (user_id, preference_key),
                INDEX idx_user (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        print("✅ 创建 user_preferences 表")

if __name__ == "__main__":
    asyncio.run(upgrade())
```

#### 2. 创建验证脚本

```bash
touch scripts/migrations/verify_v3.2.0.py
```

```python
"""验证 v3.2.0 数据库结构"""
import asyncio
from sqlalchemy import text
from app.models.db import engine

async def verify():
    async with engine.begin() as conn:
        # 检查表是否存在
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = 'user_preferences'
        """))
        exists = result.scalar() > 0
        
        if exists:
            print("✅ user_preferences 表存在")
        else:
            print("❌ user_preferences 表不存在")
            return False
        
        # 检查关键字段
        required_columns = ['user_id', 'preference_key', 'preference_value']
        for col in required_columns:
            result = await conn.execute(text(f"""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'user_preferences'
                AND column_name = '{col}'
            """))
            if result.scalar() > 0:
                print(f"  ✅ {col}")
            else:
                print(f"  ❌ {col} 不存在")
                return False
        
        return True

if __name__ == "__main__":
    asyncio.run(verify())
```

#### 3. 创建回滚脚本

```bash
touch scripts/migrations/rollback_from_v3.2.0.py
```

```python
"""回滚 v3.2.0 到 v3.1.1"""
import asyncio
from sqlalchemy import text
from app.models.db import engine

async def rollback():
    response = input("⚠️  确认删除 user_preferences 表？(yes/no): ")
    if response.lower() != "yes":
        print("取消回滚")
        return
    
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS user_preferences"))
        print("✅ 删除 user_preferences 表")

if __name__ == "__main__":
    asyncio.run(rollback())
```

#### 4. 测试迁移

```bash
# 在测试数据库执行
python scripts/migrations/upgrade_to_v3.2.0.py
python scripts/migrations/verify_v3.2.0.py

# 测试回滚
python scripts/migrations/rollback_from_v3.2.0.py
# 再次升级验证
python scripts/migrations/upgrade_to_v3.2.0.py
python scripts/migrations/verify_v3.2.0.py
```

#### 5. 更新模型类

在 `app/models/` 创建对应的 SQLAlchemy 模型：

```python
# app/models/user_preferences.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.models.base import Base

class UserPreference(Base):
    __tablename__ = "user_preferences"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False)
    preference_key = Column(String(128), nullable=False)
    preference_value = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

#### 6. 更新文档

- 更新 `docs/DATABASE_MIGRATIONS.md`
- 更新 `scripts/migrations/README.md`
- 在本文档添加版本说明

#### 7. 生产环境部署

```bash
# 备份
mysqldump -u root -p ai_trading > backup_before_v3.2.0.sql

# 升级
python scripts/migrations/upgrade_to_v3.2.0.py --production

# 验证
python scripts/migrations/verify_v3.2.0.py

# 记录版本
python scripts/migrations/version_manager.py --record v3.2.0 \
    --description "添加用户偏好设置" \
    --script "upgrade_to_v3.2.0.py"
```

### 场景 2: 修改现有表

假设你要为 v3.2.1 给 `strategies` 表添加 `priority` 字段。

#### 1. 升级脚本

```python
"""v3.1.1 → v3.2.1: 为 strategies 添加优先级字段"""
async def upgrade():
    async with engine.begin() as conn:
        # 检查字段是否存在
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
            AND table_name = 'strategies'
            AND column_name = 'priority'
        """))
        
        if result.scalar() == 0:
            await conn.execute(text("""
                ALTER TABLE strategies
                ADD COLUMN priority INT DEFAULT 0 AFTER category
            """))
            print("✅ 添加 strategies.priority 字段")
            
            # 为现有数据设置默认优先级
            await conn.execute(text("""
                UPDATE strategies
                SET priority = CASE
                    WHEN category = 'momentum' THEN 10
                    WHEN category = 'value' THEN 8
                    ELSE 5
                END
            """))
            print("✅ 初始化优先级数据")
        else:
            print("ℹ️  priority 字段已存在")
```

#### 2. 回滚脚本

```python
"""回滚 v3.2.1"""
async def rollback():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE strategies DROP COLUMN priority"))
        print("✅ 删除 strategies.priority 字段")
```

### 场景 3: 数据迁移

假设你要在 v3.3.0 中将 `tags` 字段从 TEXT 改为 JSON 类型。

#### 1. 升级脚本（含数据转换）

```python
"""v3.2.1 → v3.3.0: 转换 tags 为 JSON 类型"""
async def upgrade():
    async with engine.begin() as conn:
        # 1. 添加临时列
        await conn.execute(text("""
            ALTER TABLE strategies
            ADD COLUMN tags_json JSON NULL AFTER tags
        """))
        
        # 2. 转换数据（假设原来是逗号分隔）
        result = await conn.execute(text("SELECT id, tags FROM strategies"))
        rows = result.fetchall()
        
        for row in rows:
            if row[1]:  # tags 不为空
                tags_list = [t.strip() for t in row[1].split(',')]
                tags_json = json.dumps(tags_list)
                await conn.execute(
                    text("UPDATE strategies SET tags_json = :tags WHERE id = :id"),
                    {"tags": tags_json, "id": row[0]}
                )
        
        # 3. 删除旧列，重命名新列
        await conn.execute(text("ALTER TABLE strategies DROP COLUMN tags"))
        await conn.execute(text("ALTER TABLE strategies CHANGE tags_json tags JSON"))
        
        print("✅ 转换 tags 为 JSON 类型")
```

#### 2. 回滚脚本

```python
"""回滚 v3.3.0 (数据可能丢失)"""
async def rollback():
    print("⚠️  警告: JSON 转回 TEXT 可能导致格式变化")
    response = input("确认继续？(yes/no): ")
    if response.lower() != "yes":
        return
    
    async with engine.begin() as conn:
        # 1. 添加 TEXT 列
        await conn.execute(text("""
            ALTER TABLE strategies
            ADD COLUMN tags_text TEXT NULL AFTER tags
        """))
        
        # 2. 转换回文本
        result = await conn.execute(text("SELECT id, tags FROM strategies"))
        rows = result.fetchall()
        
        for row in rows:
            if row[1]:
                tags_list = json.loads(row[1])
                tags_text = ', '.join(tags_list)
                await conn.execute(
                    text("UPDATE strategies SET tags_text = :tags WHERE id = :id"),
                    {"tags": tags_text, "id": row[0]}
                )
        
        # 3. 替换
        await conn.execute(text("ALTER TABLE strategies DROP COLUMN tags"))
        await conn.execute(text("ALTER TABLE strategies CHANGE tags_text tags TEXT"))
        
        print("✅ 回滚 tags 为 TEXT 类型")
```

## ✅ 检查清单

在提交迁移脚本前，确认：

- [ ] 创建了 upgrade/verify/rollback 三个脚本
- [ ] 在本地数据库测试了完整的 upgrade → rollback → upgrade 流程
- [ ] 更新了 SQLAlchemy 模型类
- [ ] 更新了相关文档
- [ ] 添加了字段注释和说明
- [ ] 考虑了向后兼容性
- [ ] 评估了数据迁移的性能影响（大表）
- [ ] 准备了回滚方案

## 🎯 最佳实践

### 1. 原子操作

```python
# ✅ 好的做法：使用事务
async with engine.begin() as conn:
    await conn.execute(text("ALTER TABLE ..."))
    await conn.execute(text("UPDATE ..."))
    # 事务自动提交或回滚

# ❌ 不好的做法：多个独立操作
await conn.execute(text("ALTER TABLE ..."))
await conn.execute(text("UPDATE ..."))
```

### 2. 幂等性

```python
# ✅ 好的做法：检查后再操作
result = await conn.execute(text("""
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_name = 'strategies' AND column_name = 'priority'
"""))

if result.scalar() == 0:
    await conn.execute(text("ALTER TABLE strategies ADD COLUMN priority INT"))

# ❌ 不好的做法：直接执行
await conn.execute(text("ALTER TABLE strategies ADD COLUMN priority INT"))
```

### 3. 大数据量处理

```python
# ✅ 好的做法：批量处理
batch_size = 1000
offset = 0

while True:
    result = await conn.execute(text(f"""
        SELECT id, old_field FROM large_table
        LIMIT {batch_size} OFFSET {offset}
    """))
    rows = result.fetchall()
    
    if not rows:
        break
    
    for row in rows:
        # 处理数据
        pass
    
    offset += batch_size
    print(f"处理了 {offset} 条记录")

# ❌ 不好的做法：一次性加载所有数据
result = await conn.execute(text("SELECT * FROM large_table"))
rows = result.fetchall()  # 可能内存溢出
```

### 4. 添加索引的时机

```python
# ✅ 好的做法：先添加列，再添加数据，最后添加索引
await conn.execute(text("ALTER TABLE strategies ADD COLUMN priority INT"))
await conn.execute(text("UPDATE strategies SET priority = 5"))
await conn.execute(text("ALTER TABLE strategies ADD INDEX idx_priority (priority)"))

# ❌ 不好的做法：先加索引再插数据（性能差）
await conn.execute(text("ALTER TABLE strategies ADD COLUMN priority INT"))
await conn.execute(text("ALTER TABLE strategies ADD INDEX idx_priority (priority)"))
await conn.execute(text("UPDATE strategies SET priority = 5"))
```

## 🐛 常见问题

### Q: 升级失败怎么办？

A: 立即停止操作，从备份恢复：
```bash
mysql -u root -p ai_trading < backup_before_vX.X.X.sql
```

### Q: 忘记创建备份怎么办？

A: 如果数据未被破坏，立即备份当前状态：
```bash
mysqldump -u root -p ai_trading > emergency_backup_$(date +%Y%m%d_%H%M%S).sql
```

### Q: 可以跳过版本升级吗？

A: 不建议。应按顺序升级：v2.2.2 → v3.1.1 → v3.2.0 → v3.3.0

### Q: 如何在现有生产环境初始化版本管理？

A: 
```bash
# 1. 初始化版本表
python scripts/migrations/version_manager.py --init

# 2. 手动检查当前数据库，确定版本
python scripts/migrations/verify_v3.1.1.py

# 3. 记录当前版本
python scripts/migrations/version_manager.py --record v3.1.1 \
    --description "初始化版本记录" \
    --notes "生产环境当前版本"
```

## 📚 参考资料

- [数据库迁移完整指南](../../docs/DATABASE_MIGRATIONS.md)
- [迁移脚本 README](README.md)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
- [MySQL ALTER TABLE 语法](https://dev.mysql.com/doc/refman/8.0/en/alter-table.html)

---

**最后更新**: 2024-01
**维护者**: AI Trading Team
