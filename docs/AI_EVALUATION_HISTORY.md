# AI 评估历史功能说明

## 功能概述

AI 交易决策的评估结果现已支持持久化存储和历史管理：

- ✅ **自动保存**：每次 AI 评估后自动保存到数据库
- ✅ **历史查询**：查看最近的评估记录
- ✅ **手动删除**：支持删除单条或整批评估记录
- ✅ **批次管理**：同一次评估的标的共享批次ID

## 数据库迁移

### 方式1：使用脚本（推荐）

```bash
cd backend
chmod +x migrate_evaluation_history.sh
./migrate_evaluation_history.sh
```

### 方式2：手动执行SQL

```bash
cd backend
mysql -u root -p ai_trading < create_ai_evaluation_table.sql
```

## API 接口

### 1. 评估标的（自动保存）

**POST** `/api/v1/ai-advisor/evaluate`

```json
{
  "symbols": ["AAPL", "TSLA", "NVDA"]
}
```

**响应：**
```json
{
  "status": "ok",
  "evaluations": [
    {
      "symbol": "AAPL",
      "batch_id": "uuid-xxx",  // 批次ID，用于关联同批次评估
      "current_price": 180.50,
      "decision": {
        "direction": "LONG",
        "confidence": 75,
        "action": "BUY",
        "entry_price": 179.50,
        "stop_loss": 175.00,
        "take_profit": 190.00,
        "position_pct": 0.15,
        "risk_reward_ratio": "1:2.5",
        "scenarios": { ... },
        "catalysts": { ... }
      },
      "dimensions": { ... }
    }
  ]
}
```

### 2. 查询评估历史

**GET** `/api/v1/ai-advisor/history`

**查询参数：**
- `limit` (可选): 返回记录数，默认50，最大200
- `symbol` (可选): 按标的筛选
- `account_id` (可选): 账户ID

**响应：**
```json
{
  "status": "ok",
  "total": 10,
  "history": [
    {
      "id": 1,
      "batch_id": "uuid-xxx",
      "symbol": "AAPL",
      "current_price": 180.50,
      "direction": "LONG",
      "confidence": 75,
      "action": "BUY",
      "entry_price": 179.50,
      "stop_loss": 175.00,
      "take_profit": 190.00,
      "position_pct": 0.15,
      "risk_level": "MEDIUM",
      "reasoning": "...",
      "key_factors": [...],
      "risk_reward_ratio": "1:2.5",
      "scenarios": { ... },
      "catalysts": { ... },
      "holding_period": "2-4周",
      "dimensions": { ... },
      "created_at": "2026-02-13T10:30:00"
    }
  ]
}
```

### 3. 删除单条评估记录

**DELETE** `/api/v1/ai-advisor/history/{record_id}`

### 4. 删除整批评估记录

**DELETE** `/api/v1/ai-advisor/history/batch/{batch_id}`

**响应：**
```json
{
  "status": "ok",
  "message": "已删除 3 条记录",
  "deleted_count": 3
}
```

## 前端界面

### 历史记录展示

在 AI 交易决策页面的「评估历史」section 中：

- **卡片式布局**：每条记录显示为独立卡片
- **关键信息**：标的、价格、操作建议、置信度
- **详细指标**：入场价、止损、止盈、仓位
- **时间标记**：相对时间（刚刚、5分钟前、1天前等）
- **快速删除**：每张卡片右上角的删除按钮

### 交互特性

- ✅ 页面加载时自动获取历史记录
- ✅ 评估完成后自动刷新历史
- ✅ 悬停卡片有高亮效果
- ✅ 根据操作类型（BUY/SELL/HOLD）显示不同边框颜色
- ✅ 推理文本自动截断显示（最多2行）

## 数据模型

### AIEvaluationHistory 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| account_id | VARCHAR(64) | 账户ID |
| batch_id | VARCHAR(64) | 批次ID |
| symbol | VARCHAR(32) | 标的代码 |
| current_price | DECIMAL(20,6) | 评估时价格 |
| direction | VARCHAR(16) | 方向 (LONG/SHORT/NEUTRAL) |
| confidence | INT | 置信度 (0-100) |
| action | VARCHAR(16) | 操作 (BUY/SELL/HOLD/AVOID) |
| entry_price | DECIMAL(20,6) | 入场价 |
| stop_loss | DECIMAL(20,6) | 止损价 |
| take_profit | DECIMAL(20,6) | 止盈价 |
| position_pct | DECIMAL(10,4) | 仓位比例 |
| risk_level | VARCHAR(16) | 风险等级 |
| reasoning | TEXT | 决策理由 |
| key_factors | JSON | 关键因素 |
| risk_reward_ratio | VARCHAR(16) | 风险收益比 |
| scenarios | JSON | 情景分析 |
| catalysts | JSON | 催化剂 |
| holding_period | VARCHAR(64) | 持有周期 |
| dimensions | JSON | 多维评分 |
| created_at | DATETIME | 创建时间 |

### 索引

- `idx_eval_account_batch` (account_id, batch_id)
- `idx_eval_symbol` (symbol)
- `idx_eval_created` (created_at)

## 使用示例

### 1. 前端发起评估

```typescript
// 评估多个标的
const { data } = await client.post('/v1/ai-advisor/evaluate', {
  symbols: ['AAPL', 'TSLA', 'NVDA']
});

// 评估结果已自动保存到数据库
console.log('批次ID:', data.evaluations[0].batch_id);
```

### 2. 查看历史记录

```typescript
// 加载最近50条评估记录
const { data } = await client.get('/v1/ai-advisor/history', {
  params: { limit: 50 }
});

console.log('历史记录数:', data.total);
```

### 3. 删除记录

```typescript
// 删除单条记录
await client.delete(`/v1/ai-advisor/history/${recordId}`);

// 或删除整批记录
await client.delete(`/v1/ai-advisor/history/batch/${batchId}`);
```

## 注意事项

1. **存储策略**：每次评估都会创建新记录，不会覆盖历史
2. **批次管理**：同一次评估的所有标的共享一个 batch_id
3. **删除权限**：只能删除自己账户下的评估记录
4. **数据清理**：建议定期清理过期的评估记录（如保留最近30天）

## 后续优化建议

1. **自动清理**：添加定时任务自动清理超过30天的历史记录
2. **筛选增强**：支持按日期范围、操作类型、置信度等筛选
3. **导出功能**：支持将评估历史导出为CSV/Excel
4. **统计分析**：添加评估准确率、胜率等统计指标
5. **批注功能**：允许用户为历史记录添加个人批注

## 技术实现

### 后端

- **模型**：`app/models/ai_evaluation_history.py`
- **服务**：`app/services/ai_trade_advisor_service.py`
  - `_save_evaluation_history()` - 保存评估结果
  - `get_evaluation_history()` - 查询历史记录
  - `delete_evaluation_record()` - 删除单条记录
  - `delete_evaluation_batch()` - 删除批次记录
- **路由**：`app/routers/ai_advisor.py`
  - `GET /history` - 查询历史
  - `DELETE /history/{record_id}` - 删除单条
  - `DELETE /history/batch/{batch_id}` - 删除批次

### 前端

- **页面**：`src/views/AIAdvisorPage.vue`
- **状态管理**：`evaluationHistory` ref
- **方法**：
  - `loadHistory()` - 加载历史记录
  - `deleteHistoryRecord()` - 删除记录
  - `formatTime()` - 格式化时间显示
- **样式**：历史卡片网格布局、悬停效果、颜色编码

## 测试清单

- [ ] 评估标的后历史记录自动保存
- [ ] 历史记录页面正确显示
- [ ] 删除单条记录成功
- [ ] 删除批次记录成功
- [ ] 时间格式化正确（刚刚、分钟前、小时前等）
- [ ] 不同操作类型显示不同颜色
- [ ] 悬停效果正常
- [ ] 响应式布局适配移动端
