# Tiger API 替换 Yahoo Finance - 快速实施方案

## 阶段1：立即修复港股数据获取问题

### 问题
- 港股02513使用Yahoo Finance触发Rate Limit
- 导致技术分析失败，返回null

### 解决方案
增强MarketDataProvider，优先使用Tiger API获取港股数据

### 实施步骤

#### 1. 优化get_historical_data方法

```python
async def get_historical_data(
    self,
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    market: Optional[str] = None  # 新增：明确指定市场
) -> pd.DataFrame:
    """获取历史数据 - Tiger优先"""
    
    # Tiger API优先（支持所有市场）
    if self._tiger_quote_client and interval in ("1d", "1D", "day", "DAY"):
        try:
            print(f"[MarketData] Attempting Tiger API for {symbol}")
            df = await self._get_tiger_bars(symbol, period)
            
            if df is not None and len(df) > 0:
                print(f"[MarketData] ✓ Tiger API success for {symbol}, rows={len(df)}")
                return df
            else:
                print(f"[MarketData] Tiger API returned empty data for {symbol}")
        except Exception as e:
            print(f"[MarketData] Tiger API failed for {symbol}: {e}")
    
    # 降级到Yahoo Finance（增加延迟避免Rate Limit）
    print(f"[MarketData] Falling back to Yahoo Finance for {symbol}")
    await asyncio.sleep(1)  # 1秒延迟避免频率限制
    
    try:
        ticker = self.get_ticker(symbol)
        df = await self._run_in_executor(
            ticker.history,
            period=period,
            interval=interval
        )
        if df is not None and len(df) > 0:
            print(f"[MarketData] ✓ Yahoo Finance success for {symbol}, rows={len(df)}")
            return df
    except Exception as e:
        print(f"[MarketData] Yahoo Finance failed for {symbol}: {e}")
    
    # 返回空DataFrame
    print(f"[MarketData] ✗ All data sources failed for {symbol}")
    return pd.DataFrame()
```

#### 2. 提取Tiger bars获取逻辑

```python
async def _get_tiger_bars(
    self,
    symbol: str,
    period: str
) -> Optional[pd.DataFrame]:
    """使用Tiger API获取K线数据"""
    if not self._tiger_quote_client or not BarPeriod:
        return None
    
    end_ms = int(datetime.now().timestamp() * 1000)
    limit = self._period_to_limit(period)
    
    try:
        bars_df = await self._run_in_executor(
            self._tiger_quote_client.get_bars,
            [symbol],
            period=BarPeriod.DAY,
            end_time=end_ms,
            limit=limit,
        )
        
        if bars_df is None or len(bars_df) == 0:
            return None
        
        df = bars_df.copy()
        
        # 标准化列名
        colmap = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "time": "Time",
        }
        for k, v in colmap.items():
            if k in df.columns and v not in df.columns:
                df.rename(columns={k: v}, inplace=True)
        
        # 设置索引
        if "Time" in df.columns:
            df.index = pd.to_datetime(df["Time"], unit="ms")
            df.drop(columns=["Time"], inplace=True)
        
        # 过滤symbol
        if "symbol" in df.columns:
            df = df[df["symbol"] == symbol].drop(columns=["symbol"], errors="ignore")
        
        # 确保必需列存在
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                df[col] = pd.NA
        
        df.sort_index(inplace=True)
        return df
        
    except Exception as e:
        print(f"[MarketData] Tiger bars error for {symbol}: {e}")
        return None
```

#### 3. 增加智能重试机制

```python
async def _get_yahoo_data_with_retry(
    self,
    symbol: str,
    period: str,
    interval: str = "1d",
    max_retries: int = 3
) -> pd.DataFrame:
    """Yahoo Finance with retry and backoff"""
    
    for attempt in range(max_retries):
        try:
            # 每次重试增加延迟
            if attempt > 0:
                delay = 2 ** attempt  # 指数退避：2, 4, 8秒
                print(f"[MarketData] Yahoo retry {attempt+1}/{max_retries} for {symbol}, waiting {delay}s")
                await asyncio.sleep(delay)
            
            ticker = self.get_ticker(symbol)
            df = await self._run_in_executor(
                ticker.history,
                period=period,
                interval=interval
            )
            
            if df is not None and len(df) > 0:
                return df
                
        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e):
                print(f"[MarketData] Yahoo Rate Limit hit for {symbol}, attempt {attempt+1}")
                if attempt == max_retries - 1:
                    raise
                continue
            else:
                raise
    
    return pd.DataFrame()
```

#### 4. 优化get_current_price

```python
async def get_current_price(self, symbol: str) -> float:
    """获取当前价格 - Tiger优先"""
    
    # 优先Tiger API
    if self._tiger_quote_client:
        try:
            df = await self._run_in_executor(
                self._tiger_quote_client.get_stock_briefs,
                [symbol]
            )
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                for key in ("latest_price", "latestPrice", "close", "pre_close"):
                    if key in row and row[key] is not None:
                        price = float(row[key])
                        print(f"[MarketData] Tiger price for {symbol}: {price}")
                        return price
        except Exception as e:
            print(f"[MarketData] Tiger price failed for {symbol}: {e}")
    
    # 降级Yahoo Finance
    try:
        await asyncio.sleep(0.5)  # 延迟避免Rate Limit
        ticker = self.get_ticker(symbol)
        info = await self._run_in_executor(lambda: ticker.info)
        price = info.get('currentPrice') or info.get('regularMarketPrice', 0.0)
        print(f"[MarketData] Yahoo price for {symbol}: {price}")
        return price
    except Exception as e:
        print(f"[MarketData] Yahoo price failed for {symbol}: {e}")
        return 0.0
```

### 代码改动位置

文件：`backend/app/providers/market_data_provider.py`

需要修改的方法：
1. `get_historical_data()` - 添加Tiger优先逻辑
2. 新增 `_get_tiger_bars()` - 提取Tiger获取逻辑
3. 新增 `_get_yahoo_data_with_retry()` - 重试机制
4. `get_current_price()` - 添加延迟

### 测试验证

```bash
# 测试港股数据获取
curl "http://127.0.0.1:8090/api/v1/positions/assessment?window_days=7"

# 预期结果：
# - META: 有trend_snapshot ✓
# - PLTR: 有trend_snapshot ✓  
# - 02513: 有trend_snapshot ✓ (使用Tiger API)
```

### 预期效果

1. ✅ 港股02513使用Tiger API获取数据，避免Yahoo Rate Limit
2. ✅ 美股继续使用Tiger API（已有实现）
3. ✅ Yahoo Finance作为降级，增加重试和延迟
4. ✅ 所有持仓都能正常显示技术分析快照

### 回滚方案

如果Tiger API出现问题，系统会自动降级到Yahoo Finance，保持原有功能。

---

## 阶段2：增强缓存策略（下一步）

### 目标
减少API调用频率，降低Rate Limit风险

### 措施

1. **技术指标缓存延长**
```python
# 当前：5分钟缓存
# 优化：1小时缓存
TechnicalIndicator.timestamp >= datetime.now() - timedelta(hours=1)
```

2. **财务数据缓存延长**
```python
# 当前：每次都查询
# 优化：24小时缓存
@cache(ttl=86400)
async def get_financials(symbol: str):
    ...
```

3. **公司信息缓存延长**
```python
# 优化：7天缓存（基本信息很少变化）
@cache(ttl=604800)
async def get_company_info(symbol: str):
    ...
```

### 实施优先级

- **P0（立即）**：修复港股数据获取 - 本方案
- **P1（本周）**：增强缓存策略
- **P2（2周）**：实现Redis缓存层
- **P3（按需）**：引入第三方基本面数据

---

## 监控指标

实施后需要监控：

1. **API调用成功率**
   - Tiger API成功率：目标 > 95%
   - Yahoo Finance调用次数：目标减少50%

2. **数据获取延迟**
   - Tiger API: < 1s
   - Yahoo Finance: < 3s

3. **Rate Limit触发次数**
   - 目标：0次/天

4. **数据完整性**
   - 技术分析快照生成率：100%
   - 价格数据准确性：100%
