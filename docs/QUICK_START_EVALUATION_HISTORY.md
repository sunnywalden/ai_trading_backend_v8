# AI 评估历史功能 - 快速开始

## 🚀 快速部署

### 1. 数据库迁移

```bash
# 进入后端目录
cd /Users/admin/IdeaProjects/ai_trading_backend_v8/backend

# 执行迁移脚本（推荐）
chmod +x migrate_evaluation_history.sh
./migrate_evaluation_history.sh

# 或者手动执行SQL
mysql -u root -p ai_trading < create_ai_evaluation_table.sql
```

### 2. 重启后端服务

```bash
# 停止现有服务
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# 启动后端
cd /Users/admin/IdeaProjects/ai_trading_backend_v8/backend
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &
```

### 3. 前端无需重启

前端代码已更新，刷新页面即可看到新功能。

## ✅ 验证功能

### 1. 测试评估并保存

访问 AI 交易决策页面，输入标的（如 AAPL, TSLA）进行评估：

```
http://localhost:5173/ai-advisor
```

### 2. 查看历史记录

评估完成后，页面会自动显示「评估历史」section。

### 3. 测试删除功能

点击历史记录卡片右上角的删除图标🗑️。

### 4. API 测试

```bash
# 查询历史记录
curl http://localhost:8000/api/v1/ai-advisor/history?limit=10

# 删除单条记录
curl -X DELETE http://localhost:8000/api/v1/ai-advisor/history/1

# 删除批次记录
curl -X DELETE http://localhost:8000/api/v1/ai-advisor/history/batch/uuid-xxx
```

## 📊 功能特性

### 前端界面

- ✅ **第4步骤**：新增「评估历史」section
- ✅ **卡片展示**：每条记录独立卡片，响应式网格布局
- ✅ **颜色编码**：BUY=绿边框，SELL=红边框，HOLD=灰边框
- ✅ **时间显示**：智能相对时间（刚刚、5分钟前、1天前）
- ✅ **一键删除**：卡片右上角删除按钮
- ✅ **悬停效果**：卡片悬停高亮显示
- ✅ **自动刷新**：页面加载和评估完成后自动加载历史

### 数据持久化

- ✅ **自动保存**：每次评估后自动保存所有标的
- ✅ **批次管理**：同次评估标的共享 batch_id
- ✅ **完整信息**：保存决策、价格、指标、推理等全部数据
- ✅ **华尔街字段**：包含 R:R 比、情景分析、催化剂、持有周期

### API 接口

- ✅ `GET /api/v1/ai-advisor/history` - 查询历史（支持筛选）
- ✅ `DELETE /api/v1/ai-advisor/history/{id}` - 删除单条
- ✅ `DELETE /api/v1/ai-advisor/history/batch/{batch_id}` - 删除批次

## 🎯 使用场景

### 场景1：回顾历史决策

用户想看看昨天对 TSLA 的评估建议是什么：

1. 进入 AI 交易决策页面
2. 滚动到「评估历史」section
3. 找到 TSLA 的历史卡片
4. 查看当时的入场价、止损、止盈建议

### 场景2：对比不同时间的评估

用户想比较本周对 AAPL 的多次评估：

1. 查看评估历史
2. 找到所有 AAPL 的记录
3. 对比置信度、入场价的变化
4. 分析 AI 建议的趋势变化

### 场景3：清理旧记录

用户想删除一周前的评估记录：

1. 点击卡片右上角的🗑️图标
2. 确认删除
3. 记录从界面消失

## 🔧 故障排查

### 问题1：历史记录不显示

**检查：**
```bash
# 确认表已创建
mysql -u root -p ai_trading -e "SHOW TABLES LIKE 'ai_evaluation_history';"

# 确认后端日志
tail -f /tmp/backend.log | grep evaluation
```

### 问题2：评估后没有保存

**检查：**
```bash
# 查看数据库记录
mysql -u root -p ai_trading -e "SELECT COUNT(*) FROM ai_evaluation_history;"

# 查看后端日志中的保存记录
tail -f /tmp/backend.log | grep "已保存评估历史"
```

### 问题3：删除失败

**检查：**
- 确认 record_id 正确
- 确认 account_id 匹配
- 查看后端错误日志

## 📝 注意事项

1. **数据量控制**：建议定期清理超过30天的历史记录
2. **性能优化**：历史记录默认显示最近50条，避免一次加载过多
3. **权限隔离**：只能查看和删除自己账户的评估记录
4. **批次关联**：删除批次时会删除该批次所有标的的评估记录

## 🎉 完成！

功能已完全实现，可以开始使用了！

如有问题，请查看完整文档：
- [AI_EVALUATION_HISTORY.md](./AI_EVALUATION_HISTORY.md)
