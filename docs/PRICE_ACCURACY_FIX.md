## 快捷交易价格准确性修复 - 测试说明

### 📋 修改内容

#### 1. 价格获取逻辑修改
**文件**: `backend/app/services/quick_trade_service.py`

**修改前**:
```python
async def _get_current_price(self, symbol: str) -> float:
    try:
        price = await self.market_data.get_current_price(symbol)
        return price if price and price > 0 else 100.0  # 返回默认值
    except Exception:
        return 100.0  # 静默失败
```

**修改后**:
```python
async def _get_current_price(self, symbol: str) -> float:
    """获取当前市价 - 必须返回准确价格，否则抛出异常"""
    price = await self.market_data.get_current_price(symbol)
    
    if not price or price <= 0:
        raise ValueError(f"无法获取 {symbol} 的准确价格，当前返回值: {price}")
    
    return price
```

**影响**: 
- ✅ 确保价格数据的准确性和实时性
- ✅ 价格获取失败时明确报错，不使用错误的默认值

---

#### 2. 账户权益获取逻辑修改

**修改前**:
```python
async def _get_account_equity(self) -> float:
    try:
        equity = await self.broker.get_account_equity(account_id)
        return equity if equity > 0 else 1000000.0  # 默认值
    except Exception:
        return 1000000.0  # 静默失败
```

**修改后**:
```python
async def _get_account_equity(self) -> float:
    """获取账户权益 - 必须返回准确值，否则抛出异常"""
    try:
        account_id = settings.TIGER_ACCOUNT
        equity = await self.broker.get_account_equity(account_id)
        
        if not equity or equity <= 0:
            raise ValueError(f"账户 {account_id} 权益数据异常: {equity}")
        
        return equity
    except Exception as e:
        print(f"[QuickTradeService] 无法获取账户权益: {e}")
        raise ValueError(f"无法获取账户 {settings.TIGER_ACCOUNT} 的准确权益数据: {e}")
```

**影响**: 
- ✅ 确保交易数量计算基于真实账户数据
- ✅ 权益获取失败时明确报错

---

#### 3. 预览逻辑支持双模式

**修改后**: `preview_quick_trade()` 支持两种模式

##### 模式A: 限价单模式（有准确价格）
```json
{
  "order_mode": "LIMIT",
  "price_available": true,
  "current_price": 670.49,
  "calculated_quantity": 2135,
  "calculated_stop_loss": 95.00,
  "calculated_take_profit": 115.00,
  "estimated_position_value": 1432196.15,
  "estimated_position_ratio": 0.22
}
```

##### 模式B: 市价单模式（无准确价格）
```json
{
  "order_mode": "MARKET",
  "price_available": false,
  "current_price": null,
  "calculated_quantity": null,
  "calculated_stop_loss": null,
  "calculated_take_profit": null,
  "estimated_position_value": null,
  "estimated_position_ratio": null,
  "warning": "无法获取实时价格，将以市价单执行，不设置止盈止损"
}
```

**影响**:
- ✅ 价格获取失败时不阻塞交易，自动切换为市价单
- ✅ 市价单模式不设置止盈止损（符合产品需求）
- ✅ 明确告知用户当前使用的订单模式

---

#### 4. 信号创建支持市价单

**修改后**: `_create_signal_from_preview()` 处理 None 值

```python
signal = TradingSignal(
    signal_id=str(uuid.uuid4()),
    ...
    suggested_quantity=preview.get("calculated_quantity"),  # 可以为 None
    suggested_price=preview.get("current_price"),  # 可以为 None
    stop_loss=preview.get("calculated_stop_loss"),  # 可以为 None
    take_profit=preview.get("calculated_take_profit"),  # 可以为 None
    notes=f"{notes} | Order Mode: {order_mode}"  # 标记订单模式
)
```

**影响**:
- ✅ 数据库字段兼容 NULL 值
- ✅ 订单执行器可以识别并使用市价单模式

---

### 🧪 测试场景

#### 场景1: 正常获取价格（限价单模式）
**步骤**:
1. 调用预览接口: `GET /api/v1/strategy-runs/{run_id}/assets/META/preview`
2. Tiger API 或 Yahoo Finance 成功返回价格 670.49
3. 计算数量、止盈止损

**预期结果**:
```json
{
  "order_mode": "LIMIT",
  "price_available": true,
  "current_price": 670.49,
  "calculated_quantity": 2135,
  "calculated_stop_loss": 637.00,
  "calculated_take_profit": 771.00
}
```

---

#### 场景2: 无法获取价格（市价单模式）
**步骤**:
1. Tiger API 未配置或失败
2. Yahoo Finance 也失败（网络问题）
3. `_get_current_price()` 抛出异常
4. `preview_quick_trade()` 捕获异常，切换为市价单模式

**预期结果**:
```json
{
  "order_mode": "MARKET",
  "price_available": false,
  "current_price": null,
  "calculated_quantity": null,
  "calculated_stop_loss": null,
  "calculated_take_profit": null,
  "warning": "无法获取实时价格，将以市价单执行，不设置止盈止损"
}
```

---

#### 场景3: 账户权益获取失败
**步骤**:
1. 券商 API 连接失败
2. `_get_account_equity()` 抛出异常
3. 整个交易流程失败

**预期结果**:
```json
{
  "error": "无法获取账户 demo-account 的准确权益数据: Connection timeout"
}
```

**状态码**: 500

---

#### 场景4: 批量交易部分失败
**步骤**:
1. 批量下单 10 只股票
2. 其中 2 只无法获取价格，切换为市价单
3. 其中 1 只符号错误，完全失败

**预期结果**:
```json
{
  "total_signals": 10,
  "success_count": 9,
  "failed_count": 1,
  "signal_ids": ["uuid1", "uuid2", ...],
  "failures": [
    {
      "symbol": "INVALID",
      "error": "未找到策略运行中的标的 INVALID"
    }
  ]
}
```

---

### 🔍 调试指南

#### 1. 检查日志输出
```bash
# 后端日志中查找价格获取信息
[QuickTradeService] 获取 META 当前价格...
[MarketData] Attempting Tiger API for price of META
[MarketData] Tiger price for META: 670.49
[QuickTradeService] META 当前价格: $670.49
```

#### 2. 市价单模式日志
```bash
[QuickTradeService] 获取 META 当前价格...
[MarketData] Attempting Tiger API for price of META
[MarketData] Tiger API price failed for META: Connection timeout
[MarketData] Falling back to Yahoo Finance for price of META
[MarketData] Yahoo Finance price failed for META: Too many requests
[QuickTradeService] 无法获取 META 价格，将使用市价单模式: 无法获取 META 的准确价格
```

#### 3. 验证信号记录
```sql
-- 查看信号中的订单模式标记
SELECT signal_id, symbol, suggested_price, stop_loss, take_profit, notes
FROM trading_signals
WHERE notes LIKE '%Order Mode:%'
ORDER BY generated_at DESC
LIMIT 10;
```

**限价单示例**:
```
signal_id: abc-123
symbol: META
suggested_price: 670.49
stop_loss: 637.00
take_profit: 771.00
notes: 策略快捷交易: META [LIMIT] | Order Mode: LIMIT
```

**市价单示例**:
```
signal_id: def-456
symbol: AAPL
suggested_price: NULL
stop_loss: NULL
take_profit: NULL
notes: 策略快捷交易: AAPL [MARKET] | Order Mode: MARKET
```

---

### ✅ 验收标准

1. **价格准确性**
   - ✅ 不再出现默认价格 100.0
   - ✅ 所有价格来自真实 API（Tiger 或 Yahoo Finance）
   - ✅ 价格缓存 60 秒，保证实时性

2. **错误处理**
   - ✅ 价格获取失败时，明确返回错误信息或切换市价单
   - ✅ 账户权益获取失败时，交易流程终止并报错
   - ✅ 批量交易中部分失败不影响其他标的

3. **市价单模式**
   - ✅ 无法获取价格时自动切换市价单
   - ✅ 市价单不设置止盈止损
   - ✅ 市价单不预估交易数量
   - ✅ 信号 notes 中标记订单模式

4. **用户体验**
   - ✅ 预览接口返回 order_mode 和 price_available 字段
   - ✅ 市价单模式返回 warning 提示
   - ✅ 前端可根据 order_mode 调整 UI 显示

---

### 🚀 部署步骤

1. **备份当前代码**
   ```bash
   git add .
   git commit -m "backup: before price accuracy fix"
   ```

2. **应用修改**
   ```bash
   # 修改已完成，文件：
   # backend/app/services/quick_trade_service.py
   ```

3. **数据库兼容性检查**
   ```sql
   -- 确认字段允许 NULL
   DESCRIBE trading_signals;
   -- suggested_price, suggested_quantity, stop_loss, take_profit 应该允许 NULL
   ```

4. **重启服务**
   ```bash
   cd backend
   # 重启 FastAPI 服务
   ```

5. **冒烟测试**
   ```bash
   # 测试预览接口
   curl http://localhost:8000/api/v1/strategy-runs/{run_id}/assets/META/preview
   
   # 检查返回的 order_mode 和 price_available 字段
   ```

6. **监控告警**
   - 监控价格获取失败率
   - 监控市价单使用频率
   - 如果市价单频率过高，检查 Tiger API 配置

---

### 📝 后续优化建议

1. **价格数据源优先级配置**
   ```python
   # settings.py
   PRICE_DATA_SOURCES = ["TIGER", "YAHOO", "FALLBACK"]
   ```

2. **市价单确认机制**
   - 前端增加二次确认弹窗
   - 明确告知用户将以市价成交

3. **历史价格回退**
   - 如果实时价格失败，可考虑使用最近的历史价格（带时间戳）
   - 前端显示价格更新时间

4. **价格异常检测**
   - 价格波动超过 20% 时发出警告
   - 避免因数据错误导致的异常交易

---

### 🎯 核心改进

| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| **价格准确性** | 失败时返回 100.0 | 抛出异常或切换市价单 |
| **错误处理** | 静默失败 | 明确报错 |
| **数据可靠性** | 使用默认值 | 必须获取真实数据 |
| **用户体验** | 显示错误价格 | 提供市价单选项 |
| **风险控制** | 可能基于错误价格交易 | 保证数据准确性 |

---

**修改完成时间**: 2026-02-12  
**修改人**: AI Assistant  
**版本**: v3.0.2+price-accuracy-fix
