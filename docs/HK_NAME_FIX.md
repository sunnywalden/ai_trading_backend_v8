# 港股名称显示修复

## 问题描述

持仓评估API (`/api/v1/positions/assessment`) 返回的港股持仓中，`symbol` 字段显示的是英文名称（如 "KNOWLEDGE ATLAS"），而不是期望的中文名称（如 "智谱"）。

## 原因分析

1. Tiger API 的 `get_stock_briefs()` 返回的数据中同时包含多个名称字段：
   - `name`: 英文名称
   - `nameCN`: 中文名称
   - `name_cn`: 中文名称（备用）
   - `localSymbol`: 本地代码

2. 原代码优先使用 `name` 字段（英文），导致港股显示英文名称

3. 已获取的名称会缓存30天，即使修复代码后，旧缓存仍会返回英文名称

## 解决方案

### 1. 代码修复（已完成）

修改了 `/Users/admin/IdeaProjects/ai_trading_backend_v8/backend/app/broker/tiger_option_client.py` 第96行：

**修改前：**

```python
name = row.get('name') or row.get('nameCN') or row.get('name_cn') or row.get('localSymbol')
```

**修改后：**

```python
# 优先使用中文名称
name = row.get('nameCN') or row.get('name_cn') or row.get('localSymbol') or row.get('name')
```

### 2. 清除旧缓存

由于港股名称缓存30天，需要清除旧的英文名称缓存：

```bash
cd backend
python clear_hk_name_cache.py
```

该脚本会清除已知港股symbol的缓存。如果您的持仓包含其他港股，请编辑脚本添加对应的symbol。

### 3. 验证修复

运行测试脚本验证港股名称是否正确显示：

```bash
cd backend
python test_assessment_hk_name.py
```

或直接调用API：

```bash
curl "http://localhost:8088/api/v1/positions/assessment?force_refresh=true"
```

## API行为说明

1. **首次调用**（无缓存）：
   - 从 Tiger API 获取港股名称
   - 优先返回中文名称（`nameCN`）
   - 将名称缓存30天

2. **后续调用**（有缓存）：
   - 直接从缓存读取名称
   - 不会调用 Tiger API
   - 避免速率限制

3. **强制刷新**：
   - 使用参数 `force_refresh=true`
   - 会重新计算持仓评估
   - 但不会清除名称缓存（除非缓存过期）

## 注意事项

1. **Tiger API 速率限制**：
   - `get_stock_briefs` 接口有速率限制
   - 首次获取名称时可能较慢
   - 缓存机制可减少API调用

2. **缓存更新**：
   - 名称缓存有效期30天
   - 股票名称通常不变，长缓存时间合理
   - 如需强制更新，运行清除缓存脚本

3. **fallback 机制**：
   - 如果 Tiger API 无法返回中文名称
   - 会依次尝试 `name_cn`、`localSymbol`、`name`
   - 最坏情况返回英文名称

## 测试场景

### 场景1: 清除缓存后首次调用

```bash
# 1. 清除缓存
python clear_hk_name_cache.py

# 2. 调用API（会从Tiger获取中文名称）
curl "http://localhost:8088/api/v1/positions/assessment?force_refresh=true"
```

预期结果：港股持仓的 `symbol` 字段显示中文名称（如 "智谱"）

### 场景2: 有缓存时调用

```bash
# 直接调用API（从缓存读取）
curl "http://localhost:8088/api/v1/positions/assessment"
```

预期结果：快速返回，港股名称来自缓存

## 相关文件

- `/backend/app/broker/tiger_option_client.py`: Tiger API 客户端，获取和缓存港股名称
- `/backend/app/routers/position_macro.py`: 持仓评估API端点，使用港股名称
- `/backend/clear_hk_name_cache.py`: 清除港股名称缓存的工具脚本
- `/backend/test_assessment_hk_name.py`: 测试港股名称显示的脚本

## 常见问题

**Q: 修改代码后仍显示英文名称？**

A: 需要清除缓存。运行 `python clear_hk_name_cache.py`

**Q: 清除缓存后调用API报错 "rate limit"？**

A: Tiger API 有速率限制。等待1-2分钟后重试。

**Q: 某些港股仍显示代码而非名称？**

A: 可能该股票的 Tiger API 数据不完整。系统会 fallback 到显示代码。

**Q: 如何添加更多港股到清除缓存脚本？**

A: 编辑 `clear_hk_name_cache.py`，在 `known_symbols` 列表中添加港股代码。
