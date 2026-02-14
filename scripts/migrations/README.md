# 数据库迁移脚本

本目录包含按版本组织的数据库迁移脚本。

## 📂 目录结构

```
scripts/migrations/
├── README.md                    # 本文件
├── version_manager.py           # 版本管理工具
├── upgrade_to_v3.1.1.py        # v2.2.2 → v3.1.1 升级脚本
├── verify_v3.1.1.py            # v3.1.1 验证脚本
└── rollback_from_v3.1.1.py     # v3.1.1 回滚脚本
```

## 🚀 快速开始

### 1. 初始化版本管理

```bash
# 首次使用，初始化版本管理表
python scripts/migrations/version_manager.py --init

# 查看当前版本
python scripts/migrations/version_manager.py --current
```

### 2. 升级数据库

```bash
# 开发/测试环境
python scripts/migrations/upgrade_to_v3.1.1.py

# 生产环境（需要确认）
python scripts/migrations/upgrade_to_v3.1.1.py --production
```

### 3. 验证升级

```bash
# 验证数据库结构
python scripts/migrations/verify_v3.1.1.py
```

### 4. 记录版本

```bash
# 升级成功后记录版本
python scripts/migrations/version_manager.py --record v3.1.1 \
    --description "添加策略通知和信号性能跟踪" \
    --script "upgrade_to_v3.1.1.py"
```

## 📋 版本历史

| 版本 | 发布日期 | 主要变更 | 脚本 |
|------|---------|---------|------|
| v3.1.2 | 2024-02 | 修复联调接口，优化导航，完善迁移工具 | (应用代码逻辑变更) |
| v3.1.1 | 2024-01 | 添加策略通知、信号性能跟踪、扩展15个策略 | upgrade_to_v3.1.1.py |
| v2.2.2 | 2023-12 | 基础版本 | - |

## 🔧 升级流程

### 标准升级流程

1. **备份数据库**
   ```bash
   # MySQL
   mysqldump -u root -p ai_trading > backup_$(date +%Y%m%d).sql
   
   # SQLite
   cp ai_trading.db ai_trading_backup_$(date +%Y%m%d).db
   ```

2. **测试环境验证**
   ```bash
   # 在测试环境执行升级
   python scripts/migrations/upgrade_to_v3.1.1.py
   
   # 验证结构
   python scripts/migrations/verify_v3.1.1.py
   
   # 运行应用测试
   pytest tests/
   ```

3. **生产环境升级**
   ```bash
   # 停止应用服务
   systemctl stop ai_trading
   
   # 备份数据库
   mysqldump -u root -p ai_trading > backup_prod_$(date +%Y%m%d_%H%M%S).sql
   
   # 执行升级
   python scripts/migrations/upgrade_to_v3.1.1.py --production
   
   # 验证结构
   python scripts/migrations/verify_v3.1.1.py
   
   # 记录版本
   python scripts/migrations/version_manager.py --record v3.1.1
   
   # 启动应用
   systemctl start ai_trading
   
   # 监控日志
   tail -f logs/app.log
   ```

4. **回滚（如需要）**
   ```bash
   # 停止应用
   systemctl stop ai_trading
   
   # 执行回滚
   python scripts/migrations/rollback_from_v3.1.1.py --confirm
   
   # 记录回滚
   python scripts/migrations/version_manager.py --rollback v3.1.1
   
   # 启动应用
   systemctl start ai_trading
   ```

## 📝 v3.1.1 升级详情

### 新增表

1. **strategy_notifications** - 策略通知记录
   - 支持多渠道通知（企业微信、邮件、钉钉）
   - 记录发送状态和时间
   - 关联 strategy_runs

2. **signal_performance** - 信号性能跟踪
   - 记录信号的盈亏情况
   - 计算持仓时间
   - 胜率统计

### 新增字段

1. **strategy_run_assets**
   - `action` VARCHAR(16) - 操作类型（buy/sell/hold）
   - `direction` VARCHAR(16) - 方向（long/short）

2. **trading_signals**
   - `strategy_id` VARCHAR(64) - 关联策略ID
   - 索引 `idx_signal_strategy`

### 性能优化

- 添加关键索引提升查询性能
- 优化通知表的查询效率
- 改进信号跟踪的数据结构

## 🛠️ 版本管理工具

### version_manager.py

数据库版本跟踪工具，防止重复升级和追踪历史。

```bash
# 查看当前版本
python scripts/migrations/version_manager.py --current

# 查看历史记录
python scripts/migrations/version_manager.py --history

# 记录新版本
python scripts/migrations/version_manager.py --record v3.1.1 \
    --description "添加通知和性能跟踪"

# 记录回滚
python scripts/migrations/version_manager.py --rollback v3.1.1
```

### schema_versions 表结构

```sql
CREATE TABLE schema_versions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    version VARCHAR(32) NOT NULL UNIQUE,
    description VARCHAR(256) NULL,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    rollback_at DATETIME NULL,
    script_name VARCHAR(128) NULL,
    checksum VARCHAR(64) NULL,
    status VARCHAR(16) DEFAULT 'applied',
    notes TEXT NULL
);
```

## ⚠️ 注意事项

### 安全提示

1. **始终备份** - 升级前务必完整备份数据库
2. **测试先行** - 在测试环境充分验证后再升级生产
3. **维护窗口** - 生产环境升级选择低峰期
4. **回滚准备** - 确保回滚脚本可用且已测试

### 常见问题

**Q: 升级失败怎么办？**
A: 立即停止应用，从备份恢复，查看错误日志，联系技术支持

**Q: 可以跳过版本升级吗？**
A: 不建议，应按顺序逐个版本升级，确保数据一致性

**Q: 升级会影响现有数据吗？**
A: v3.1.1 升级仅添加新表和新字段，不修改现有数据

**Q: 回滚会丢失数据吗？**
A: 是的，v3.1.1 新增的通知记录和性能数据会丢失

## 📚 相关文档

- [数据库迁移完整指南](../../docs/DATABASE_MIGRATIONS.md)
- [后端设计文档](../../docs/BACKEND_DESIGN.md)
- [API文档](../../docs/API.md)

## 🤝 贡献指南

### 添加新的迁移脚本

1. 创建升级脚本 `upgrade_to_vX.X.X.py`
2. 创建验证脚本 `verify_vX.X.X.py`
3. 创建回滚脚本 `rollback_from_vX.X.X.py`
4. 更新本 README
5. 更新 `docs/DATABASE_MIGRATIONS.md`

### 脚本命名规范

```
upgrade_to_v{major}.{minor}.{patch}.py      # 升级脚本
verify_v{major}.{minor}.{patch}.py          # 验证脚本
rollback_from_v{major}.{minor}.{patch}.py   # 回滚脚本
```

### 代码规范

- 使用异步 SQLAlchemy
- 包含详细注释
- 提供友好的用户提示
- 记录所有变更操作
- 实现错误处理和事务回滚

## 📞 支持

遇到问题？

1. 查看日志文件
2. 运行验证脚本
3. 查阅完整文档
4. 联系开发团队

---

**最后更新**: 2024-01
**维护者**: AI Trading Team
