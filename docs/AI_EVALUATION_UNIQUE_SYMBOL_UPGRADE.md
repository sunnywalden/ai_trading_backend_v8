# AI 评估历史 - 唯一标的模式升级

## 变更概述

从**批次历史模式**升级为**唯一标的模式**。每个标的(symbol)只保留最新的一次评估结果，再次评估时自动覆盖旧记录。

## 主要变更

### 1. 数据库模型 (ai_evaluation_history.py)
- ❌ 删除 `batch_id` 字段
- ✅ 添加 `updated_at` 字段（自动记录更新时间）
- ✅ 添加唯一约束 `UNIQUE(account_id, symbol)`
- ✅ 删除原有的 `idx_eval_account_batch` 索引

### 2. 后端服务 (ai_trade_advisor_service.py)
- ✅ `evaluate_multiple()` 移除 batch_id 生成和附加逻辑
- ✅ `_save_evaluation_history()` 改为 **UPSERT** 模式
  - 使用 `INSERT ... ON DUPLICATE KEY UPDATE`
  - 当 (account_id, symbol) 已存在时，更新记录而非插入
- ✅ `get_evaluation_history()` 移除 batch_id 返回字段
- ❌ 删除 `delete_evaluation_batch()` 方法（不再需要批量删除）

### 3. API 路由 (ai_advisor.py)
- ❌ 删除 `DELETE /history/batch/{batch_id}` 端点
- ✅ 保留 `DELETE /history/{id}` 端点（单条删除）
- ✅ 保留 `GET /history` 端点（查询历史）

### 4. 前端 (AIAdvisorPage.vue)
- ✅ 无需修改（前端已经是简化的单记录显示模式）

## 数据迁移

### 运行迁移脚本

```bash
cd /Users/admin/IdeaProjects/ai_trading_backend_v8/backend
python scripts/migrate_evaluation_to_unique_symbol.py
```

### 迁移步骤说明

1. **清理重复数据**: 每个 (account_id, symbol) 只保留 `created_at` 最新的一条记录
2. **删除旧索引**: 移除 `idx_eval_account_batch`
3. **删除 batch_id 列**
4. **添加 updated_at 列**: 自动记录更新时间
5. **添加唯一约束**: `UNIQUE(account_id, symbol)`

## 使用示例

### 后端 - 保存评估结果

```python
# 第一次评估 AAPL
await svc.evaluate_multiple(["AAPL"], save_history=True)
# → 插入新记录

# 再次评估 AAPL
await svc.evaluate_multiple(["AAPL"], save_history=True)
# → 自动覆盖旧记录，更新 updated_at
```

### 后端 - 查询历史

```python
# 获取所有评估历史（每个symbol只有一条最新记录）
history = await svc.get_evaluation_history(account_id="DU1234567")

# 查询特定标的
history = await svc.get_evaluation_history(account_id="DU1234567", symbol="AAPL")
```

### API 调用

```bash
# 评估标的（自动保存/覆盖）
POST /v1/ai-advisor/evaluate
{
  "symbols": ["AAPL", "TSLA"],
  "save_history": true
}

# 查询历史
GET /v1/ai-advisor/history?limit=50

# 删除单条记录
DELETE /v1/ai-advisor/history/{record_id}
```

## 行为变化

### 之前（批次模式）
- 每次评估生成新的 `batch_id`
- 同一标的可以有多条历史记录
- 支持按批次删除
- 需要手动管理历史记录堆积

### 现在（唯一标的模式）
- 每次评估自动覆盖同一标的的旧记录
- 每个标的只有一条最新评估
- 只支持单条删除
- 自动保持数据简洁，无需清理

## 优势

1. **数据简洁**: 自动保留最新评估，无需手动清理
2. **性能优化**: 数据量恒定，查询更快
3. **逻辑清晰**: 符合"再次评估覆盖旧记录"的直观语义
4. **降低复杂度**: 移除批次概念，代码更简单

## 注意事项

⚠️ **数据丢失警告**: 
- 运行迁移脚本后，每个标的只保留最新一条记录
- 所有历史评估记录将被删除
- 如需保留完整历史，请在迁移前备份数据库

⚠️ **API 兼容性**:
- `DELETE /history/batch/{batch_id}` 端点已删除
- 响应中不再包含 `batch_id` 字段
- 如有外部系统依赖旧API，需同步更新

## 回滚方案

如需回滚到批次模式：

1. 恢复数据库备份
2. 从 git 历史恢复以下文件：
   - `backend/app/models/ai_evaluation_history.py`
   - `backend/app/services/ai_trade_advisor_service.py`
   - `backend/app/routers/ai_advisor.py`

## 测试检查

- [ ] 运行迁移脚本无错误
- [ ] 数据库表结构正确（有 updated_at，无 batch_id，有唯一约束）
- [ ] 评估多个标的，数据正确保存
- [ ] 再次评估相同标的，旧记录被覆盖
- [ ] 查询评估历史返回正确数据
- [ ] 删除单条记录功能正常
- [ ] 前端显示评估历史正常
- [ ] 前端删除记录功能正常

## 相关文件

### 后端
- `backend/app/models/ai_evaluation_history.py` - 数据模型
- `backend/app/services/ai_trade_advisor_service.py` - 服务层逻辑
- `backend/app/routers/ai_advisor.py` - API 路由
- `backend/scripts/migrate_evaluation_to_unique_symbol.py` - 迁移脚本

### 前端
- `src/views/AIAdvisorPage.vue` - AI 分析页面（无需修改）

## 更新时间

2024年（根据实际时间调整）
