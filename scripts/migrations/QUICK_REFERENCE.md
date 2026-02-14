# 数据库迁移快速参考

## 🎯 常用命令

### 查看版本信息
```bash
# 查看当前版本
python scripts/migrations/version_manager.py --current

# 查看历史记录
python scripts/migrations/version_manager.py --history
```

### 开发/测试环境升级
```bash
# 1. 升级到 v3.1.2 (包含 v3.1.1 变更)
python scripts/migrations/upgrade_to_v3.1.1.py
python scripts/migrations/verify_v3.1.1.py
python scripts/migrations/version_manager.py --record v3.1.1

# 2. 记录当前版本 v3.1.2
python scripts/migrations/version_manager.py --record v3.1.2 --description "同步 v3.1.2 代码版本"
```

### 生产环境升级（完整流程）
```bash
# 1. 备份数据库
mysqldump -u root -p ai_trading > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. 停止应用（可选）
systemctl stop ai_trading

# 3. 执行升级（需要确认）
python scripts/migrations/upgrade_to_v3.1.1.py --production

# 4. 验证结果
python scripts/migrations/verify_v3.1.1.py

# 5. 记录版本记录
python scripts/migrations/version_manager.py --record v3.1.1
python scripts/migrations/version_manager.py --record v3.1.2 --description "同步 v3.1.2 代码版本"

# 6. 重启应用
systemctl start ai_trading

# 7. 监控日志
tail -f logs/app.log
```

### 回滚操作
```bash
# 回滚到 v3.1.1 之前的版本
python scripts/migrations/rollback_from_v3.1.1.py --confirm

# 记录回滚
python scripts/migrations/version_manager.py --rollback v3.1.1
```

### 测试迁移脚本
```bash
# 运行自动化测试
./scripts/migrations/test_migration.sh

# 手动测试流程
# 1. 升级
python scripts/migrations/upgrade_to_v3.1.1.py

# 2. 验证
python scripts/migrations/verify_v3.1.1.py

# 3. 回滚
python scripts/migrations/rollback_from_v3.1.1.py --confirm

# 4. 再次升级（测试幂等性）
python scripts/migrations/upgrade_to_v3.1.1.py
```

## 📋 v3.1.1 变更清单

### 新增表
- ✅ `strategy_notifications` - 策略通知记录
- ✅ `signal_performance` - 信号性能跟踪

### 新增字段
- ✅ `strategy_run_assets.action` - 操作类型
- ✅ `strategy_run_assets.direction` - 方向
- ✅ `trading_signals.strategy_id` - 关联策略

### 新增索引
- ✅ `strategy_notifications.idx_notif_run`
- ✅ `strategy_notifications.idx_notif_status`
- ✅ `signal_performance.idx_perf_signal`
- ✅ `signal_performance.idx_perf_strategy`
- ✅ `trading_signals.idx_signal_strategy`

## ⚠️ 注意事项

### 升级前
- [ ] 完整备份数据库
- [ ] 在测试环境验证
- [ ] 评估停机时间
- [ ] 通知相关人员

### 升级后
- [ ] 运行验证脚本
- [ ] 检查应用日志
- [ ] 验证关键功能
- [ ] 监控性能指标

### 回滚时
- [ ] 确认数据丢失范围
- [ ] 备份当前状态
- [ ] 逐步验证功能
- [ ] 记录问题原因

## 🐛 故障排除

### 升级失败
```bash
# 1. 查看错误日志
tail -n 100 logs/app.log

# 2. 从备份恢复
mysql -u root -p ai_trading < backup_YYYYMMDD_HHMMSS.sql

# 3. 检查数据库连接
python -c "from app.models.db import engine; import asyncio; asyncio.run(engine.connect())"
```

### 验证失败
```bash
# 手动检查表结构
mysql -u root -p ai_trading -e "SHOW CREATE TABLE strategy_notifications\G"
mysql -u root -p ai_trading -e "SHOW CREATE TABLE signal_performance\G"
mysql -u root -p ai_trading -e "SHOW COLUMNS FROM strategy_run_assets\G"
```

### 版本不一致
```bash
# 手动同步版本记录
python scripts/migrations/version_manager.py --record v3.1.1 \
    --notes "手动修复版本记录"
```

## 📚 相关文档

| 文档 | 说明 |
|------|------|
| [DATABASE_MIGRATIONS.md](../../docs/DATABASE_MIGRATIONS.md) | 完整的迁移指南和表结构 |
| [README.md](README.md) | 迁移脚本详细文档 |
| [WORKFLOW.md](WORKFLOW.md) | 开发者工作流程 |

## 📞 获取帮助

1. 查看日志文件
2. 运行验证脚本诊断
3. 查阅完整文档
4. 联系技术团队

---

**提示**: 将此文件保存为书签，方便日常使用！
