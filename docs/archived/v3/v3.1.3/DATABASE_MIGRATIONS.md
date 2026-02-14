# 数据库迁移指南

## 📋 版本历史

| 版本 | 发布日期 | 主要变更 | 迁移脚本 |
|------|---------|---------|---------|
| **v3.1.1** | 2026-02-14 | 策略库扩充 (15个策略)、策略运行管理、信号性能追踪 | `migrations/v3.1.1_upgrade.py` |
| v2.2.2 | 2025-12 | 持仓评估、宏观风险、交易日志 | - |

---

## 🎯 快速升级指南

### 从 v2.2.2 升级到 v3.1.1

```bash
# 1. 备份数据库（重要！）
mysqldump -u root -p ai_trading > backup_v2.2.2_$(date +%Y%m%d).sql

# 2. 执行升级脚本
cd /path/to/ai_trading_backend_v8
source .venv/bin/activate
python scripts/migrations/upgrade_to_v3.1.1.py

# 3. 验证升级
python scripts/migrations/verify_v3.1.1.py

# 4. 初始化新增的15个策略
python scripts/init_strategies.py
```

### 全新安装 v3.1.1

```bash
# 直接运行初始化脚本（包含完整表结构）
python scripts/init_db.py
python scripts/init_strategies.py
```

---

## 📊 v3.1.1 表结构概览

### 策略管理相关表

#### `strategies` - 策略定义表
```sql
CREATE TABLE strategies (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    style VARCHAR(32) NULL,
    description TEXT NULL,
    is_builtin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    tags JSON NULL,
    version INT DEFAULT 1,
    default_params JSON NULL,
    signal_sources JSON NULL,
    risk_profile JSON NULL,
    last_run_status VARCHAR(32) NULL,
    last_run_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_strategy_style (style),
    INDEX idx_strategy_builtin (is_builtin),
    INDEX idx_strategy_active (is_active)
);
```

#### `strategy_runs` - 策略运行记录表
```sql
CREATE TABLE strategy_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    strategy_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    phase VARCHAR(32) NULL,
    progress INT DEFAULT 0,
    attempt INT DEFAULT 1,
    error_message TEXT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    celery_task_id VARCHAR(128) NULL,
    request_params JSON NULL,
    timeline JSON NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE,
    INDEX idx_run_strategy (strategy_id),
    INDEX idx_run_account (account_id),
    INDEX idx_run_status (status),
    INDEX idx_run_started (started_at)
);
```

#### `historical_strategy_runs` - 历史运行归档表
```sql
CREATE TABLE historical_strategy_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL UNIQUE,
    strategy_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    hits INT NULL,
    hit_rate DECIMAL(5,2) NULL,
    avg_signal_strength DECIMAL(5,2) NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    archived_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_hist_run_strategy (strategy_id),
    INDEX idx_hist_run_account (account_id),
    INDEX idx_hist_run_finished (finished_at)
);
```

#### `strategy_run_assets` - 策略信号结果表 ⭐ 新增字段
```sql
CREATE TABLE strategy_run_assets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    signal_strength DECIMAL(5,2) NULL,
    weight DECIMAL(5,2) NULL,
    action VARCHAR(16) NULL,           -- 新增：BUY/SELL/HOLD
    direction VARCHAR(16) NULL,        -- 新增：LONG/SHORT
    risk_flags JSON NULL,
    notes TEXT NULL,
    signal_dimensions JSON NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES strategy_runs(run_id) ON DELETE CASCADE,
    INDEX idx_asset_run (run_id),
    INDEX idx_asset_symbol (symbol)
);
```

#### `strategy_run_logs` - 策略执行日志表
```sql
CREATE TABLE strategy_run_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    level VARCHAR(16) NOT NULL,
    message TEXT NOT NULL,
    phase VARCHAR(32) NULL,
    metadata JSON NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_log_run (run_id),
    INDEX idx_log_created (created_at)
);
```

#### `strategy_notifications` - 策略通知表 ⭐ 新增
```sql
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
    INDEX idx_notif_status (status)
);
```

### 交易信号相关表

#### `trading_signals` - 交易信号表 ⭐ 新增 strategy_id
```sql
CREATE TABLE trading_signals (
    id VARCHAR(64) PRIMARY KEY,
    strategy_id VARCHAR(64) NULL,     -- 新增：关联策略
    symbol VARCHAR(32) NOT NULL,
    signal_type VARCHAR(32) NOT NULL,
    action VARCHAR(16) NOT NULL,
    strength DECIMAL(5,2) NULL,
    price DECIMAL(10,2) NULL,
    timestamp DATETIME NOT NULL,
    timeframe VARCHAR(16) NULL,
    expires_at DATETIME NULL,
    metadata JSON NULL,
    status VARCHAR(16) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_signal_symbol (symbol),
    INDEX idx_signal_type (signal_type),
    INDEX idx_signal_strategy (strategy_id),
    INDEX idx_signal_timestamp (timestamp),
    INDEX idx_signal_status (status)
);
```

#### `signal_performance` - 信号性能追踪表 ⭐ 新增
```sql
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
    FOREIGN KEY (signal_id) REFERENCES trading_signals(id) ON DELETE CASCADE,
    INDEX idx_perf_signal (signal_id),
    INDEX idx_perf_strategy (strategy_id),
    INDEX idx_perf_symbol (symbol),
    INDEX idx_perf_closed (closed_at)
);
```

### 其他表（v2.2.2 保持不变）

以下表结构在 v3.1.1 中保持不变：
- `symbol_behavior_stats` - 行为统计
- `symbol_risk_profile` - 风险配置
- `macro_risk_scores` - 宏观风险评分
- `macro_indicators` - 宏观指标
- `geopolitical_events` - 地缘政治事件
- `technical_indicators` - 技术指标
- `position_scores` - 持仓评分
- `position_trend_snapshots` - 趋势快照
- `symbol_profile_cache` - 标的信息缓存
- `trading_plans` - 交易计划
- `price_alerts` - 价格告警
- `alert_history` - 告警历史
- `equity_snapshots` - 权益快照
- `trade_journal` - 交易日志
- `trade_pnl_attribution` - 盈亏归因
- `notification_logs` - 通知日志
- `audit_logs` - 审计日志
- `ai_evaluation_history` - AI 评估历史

---

## 🔧 v3.1.1 主要变更详情

### 1. 策略库扩充
- **新增 12 个内置策略**（从 3 个扩展到 15 个）
- 新增策略类别：均值回归、趋势跟踪、多因子、防御、波动率、宏观对冲
- 每个策略包含完整的参数配置和风险配置

### 2. 策略运行管理增强
- 支持异步策略运行（通过 Celery 任务队列）
- 运行状态实时追踪（queued/executing/completed/failed）
- 运行进度百分比显示
- 完整的运行时间线记录
- 自动归档历史运行记录

### 3. 信号管理优化
- `trading_signals` 表新增 `strategy_id` 字段，关联策略来源
- `strategy_run_assets` 表新增 `action` 和 `direction` 字段
- 新增 `signal_performance` 表追踪信号实际盈亏表现
- 支持信号强度、权重、风险标记等多维度信息

### 4. 通知系统
- 新增 `strategy_notifications` 表
- 支持多通道通知（邮件、Slack、微信等）
- 通知状态追踪和失败重试

### 5. 数据一致性
- 所有外键关系使用 `ON DELETE CASCADE`，确保数据清理一致性
- 所有时间字段统一使用 `DATETIME` 类型
- JSON 类型字段用于存储灵活的结构化数据

---

## ⚠️ 升级注意事项

### 必须备份！
升级前**必须**完整备份数据库：
```bash
# MySQL
mysqldump -u root -p ai_trading > backup_before_v3.1.1.sql

# SQLite（开发环境）
cp demo.db demo_backup_$(date +%Y%m%d).db
```

### 破坏性变更
v3.1.1 包含以下破坏性变更：

1. **`strategy_run_assets` 表新增必需字段**
   - 旧数据的 `action` 和 `direction` 将设为 NULL
   - 建议运行数据修复脚本填充默认值

2. **`strategies` 表结构变化**
   - `tags` 改为 JSON 类型（原 TEXT）
   - `default_params`、`signal_sources`、`risk_profile` 改为 JSON 类型

3. **可能的索引重建**
   - 升级脚本会创建新索引，大表可能耗时较长

### 兼容性检查
升级后运行以下检查：
```bash
# 检查表结构
python scripts/migrations/verify_v3.1.1.py

# 检查数据完整性
python scripts/check_db_data.py

# 测试策略运行
python scripts/check_signals.py
```

---

## 🛠️ 迁移脚本说明

### `upgrade_to_v3.1.1.py`
执行以下操作：
1. 添加新表（`strategy_notifications`, `signal_performance`）
2. 修改现有表（`strategy_run_assets` 新增字段）
3. 创建新索引
4. 数据类型转换（TEXT → JSON）
5. 外键约束添加

### `verify_v3.1.1.py`
验证以下内容：
1. 所有必需表是否存在
2. 表结构是否正确（列、类型、索引）
3. 外键约束是否有效
4. 数据完整性检查

### `rollback_from_v3.1.1.py`（可选）
回滚到 v2.2.2：
1. 删除新增表
2. 恢复修改的表结构
3. 删除新增索引

**注意**：回滚会丢失 v3.1.1 新增的数据！

---

## 📝 最佳实践

### 开发环境
```bash
# 1. 使用 SQLite 快速测试
export DATABASE_URL="sqlite+aiosqlite:///demo.db"

# 2. 初始化完整数据库
python scripts/init_db.py

# 3. 测试升级流程
python scripts/migrations/upgrade_to_v3.1.1.py
```

### 测试环境
```bash
# 1. 克隆生产数据到测试库
mysqldump prod_db | mysql test_db

# 2. 在测试库执行升级
python scripts/migrations/upgrade_to_v3.1.1.py --db test_db

# 3. 验证数据一致性
python scripts/migrations/verify_v3.1.1.py --db test_db
```

### 生产环境
```bash
# 1. 维护窗口（建议非交易时间）
# 2. 完整备份
mysqldump -u root -p ai_trading > backup_prod_$(date +%Y%m%d_%H%M%S).sql

# 3. 执行升级（使用事务）
python scripts/migrations/upgrade_to_v3.1.1.py --production

# 4. 验证
python scripts/migrations/verify_v3.1.1.py

# 5. 监控应用日志
tail -f logs/app.log

# 6. 如有问题立即回滚
mysql -u root -p ai_trading < backup_prod_*.sql
```

---

## 🔍 故障排查

### 升级失败
```bash
# 查看升级日志
cat logs/migration_v3.1.1.log

# 检查数据库连接
python -c "from app.models.db import engine; print(engine.url)"

# 手动回滚
mysql -u root -p ai_trading < backup_before_v3.1.1.sql
```

### 表结构不匹配
```bash
# 查看实际表结构
mysql -u root -p ai_trading -e "DESCRIBE strategies;"

# 对比目标结构
cat docs/DATABASE_MIGRATIONS.md | grep "CREATE TABLE strategies"

# 手动修复
mysql -u root -p ai_trading < scripts/migrations/fix_strategies_table.sql
```

### 数据不一致
```bash
# 检查外键约束
python scripts/check_db_data.py --check-fk

# 修复孤立记录
python scripts/fix_orphaned_records.py

# 重建索引
python scripts/rebuild_indexes.py
```

---

## 📚 参考文档

- [BACKEND_DESIGN.md](BACKEND_DESIGN.md) - 后端架构设计
- [API.md](API.md) - API 接口文档
- [STRATEGY_LIBRARY_DESIGN.md](STRATEGY_LIBRARY_DESIGN.md) - 策略库设计

---

**最后更新**: 2026-02-14  
**维护者**: AI Trading Team
