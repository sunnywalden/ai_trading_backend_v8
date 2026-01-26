# 港股名称显示修复总结

## 修复内容

已修复持仓评估API返回的港股名称显示问题，使其优先显示中文名称（如"智谱"）而非英文名称（如"KNOWLEDGE ATLAS"）。

## 修改的文件

### 1. 核心修复
- **文件**: `backend/app/broker/tiger_option_client.py`
- **行数**: 第96行
- **改动**: 调整从Tiger API获取港股名称时的字段优先级，优先使用`nameCN`（中文名称）

### 2. 新增工具脚本
- **文件**: `backend/clear_hk_name_cache.py`
- **功能**: 清除已缓存的旧港股名称，以便重新从API获取中文名称

### 3. 新增测试脚本
- **文件**: `backend/test_assessment_hk_name.py`
- **功能**: 测试持仓评估API返回的港股名称是否正确显示中文

### 4. 新增文档
- **文件**: `backend/docs/HK_NAME_FIX.md`
- **内容**: 详细的问题分析、解决方案和使用说明

### 5. 更新主文档
- **文件**: `README.md`
- **改动**: 在文档列表中添加港股名称修复文档的链接

## 使用步骤

### 第1步：清除旧缓存（必须）

由于港股名称有30天缓存，需要清除旧的英文名称：

```bash
cd backend
python clear_hk_name_cache.py
```

如果您的持仓包含脚本中未列出的港股，请编辑该脚本添加对应的symbol。

### 第2步：验证修复

有两种方式验证修复：

**方式1：运行测试脚本**

```bash
cd backend
python test_assessment_hk_name.py
```

**方式2：直接调用API**

```bash
# 确保服务已启动
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088

# 调用持仓评估API
curl "http://localhost:8088/api/v1/positions/assessment?force_refresh=true"
```

### 第3步：检查结果

在返回的JSON中，港股持仓的`symbol`字段应该显示中文名称：

```json
{
  "positions": [
    {
      "symbol": "智谱",  // ✓ 正确：显示中文名称
      "quantity": 500,
      "market_value": 117400,
      ...
    }
  ]
}
```

## 技术细节

### Tiger API字段说明

Tiger API的`get_stock_briefs()`返回的港股数据包含多个名称字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `nameCN` | 中文名称（首选） | "智谱清言" |
| `name_cn` | 中文名称（备用） | "智谱清言" |
| `localSymbol` | 本地代码 | "02513" |
| `name` | 英文名称 | "KNOWLEDGE ATLAS" |

### 修复前后对比

**修复前：**
```python
name = row.get('name') or row.get('nameCN') or ...
# 优先使用 name (英文名称)
```

**修复后：**
```python
name = row.get('nameCN') or row.get('name_cn') or row.get('localSymbol') or row.get('name')
# 优先使用 nameCN (中文名称)
```

### 缓存机制

1. **缓存键**: `hk_stock_name:{symbol}` (例如: `hk_stock_name:02513`)
2. **缓存时长**: 30天
3. **缓存原因**: 减少API调用，避免速率限制
4. **缓存更新**: 自动过期后重新获取，或手动清除

## 注意事项

1. **API速率限制**: Tiger API有调用频率限制，首次获取名称时可能较慢
2. **缓存必须清除**: 修改代码后，必须清除旧缓存才能生效
3. **fallback机制**: 如果无法获取中文名称，会依次尝试备用字段，最坏情况返回英文名称

## 相关链接

- 详细文档: [backend/docs/HK_NAME_FIX.md](backend/docs/HK_NAME_FIX.md)
- 清除缓存脚本: [backend/clear_hk_name_cache.py](backend/clear_hk_name_cache.py)
- 测试脚本: [backend/test_assessment_hk_name.py](backend/test_assessment_hk_name.py)
- Tiger API文档: [Tiger Open API](https://quant.itigerup.com/openapi/zh/python/)

## 问题排查

如果修复后仍显示英文名称，请按以下步骤排查：

1. ✓ 确认已清除缓存（运行`clear_hk_name_cache.py`）
2. ✓ 确认服务已重启（使用最新代码）
3. ✓ 使用`force_refresh=true`参数调用API
4. ✓ 检查Tiger API是否返回`nameCN`字段（查看日志）
5. ✓ 如有速率限制错误，等待1-2分钟后重试

如问题持续，请查看详细文档或联系技术支持。
