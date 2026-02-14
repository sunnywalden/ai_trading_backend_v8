# 策略库扩充设计文档

> **AI量化交易闭环系统** - Strategy Library Expansion Design  
> 版本：V9.1 | 更新日期：2026-02-14

---

## 1. 策略库概览

### 1.1 策略分类

基于华尔街顶级量化机构实践，将策略库扩充为 **12 大类量化策略**，覆盖全市场环境：

| 类别 | 策略数 | 适用市场 | 风险等级 | 参考机构 |
|------|--------|----------|----------|----------|
| 均值回归 (Mean Reversion) | 2 | 震荡市 | MEDIUM | BlackRock |
| 趋势跟踪 (Trend Following) | 2 | 趋势市 | MEDIUM | Bridgewater |
| 多因子 (Multi-Factor) | 2 | 全市场 | LOW-MEDIUM | AQR |
| 防御策略 (Defensive) | 2 | 熊市/危机 | LOW | Citadel |
| 波动率策略 (Volatility) | 2 | 高波动 | HIGH | Susquehanna |
| 宏观对冲 (Macro Hedge) | 2 | 周期转换 | MEDIUM | Bridgewater |

### 1.2 策略库架构

```
策略库 (Strategy Library)
├── 内置策略 (Builtin Strategies)
│   ├── 均值回归
│   │   ├── 布林带均值回归 (Bollinger Bands Mean Reversion)
│   │   └── 配对交易 (Pairs Trading)
│   ├── 趋势跟踪
│   │   ├── 突破动量 (Breakout Momentum)
│   │   └── 黄金交叉 (Golden Cross)
│   ├── 多因子
│   │   ├── Fama-French 三因子
│   │   └── 动量+质量 (Momentum + Quality)
│   ├── 防御策略
│   │   ├── 低波动率 (Low Volatility)
│   │   └── 尾部对冲 (Tail Hedge)
│   ├── 波动率策略
│   │   ├── 铁鹰期权 (Iron Condor)
│   │   └── 波动率套利 (Volatility Arbitrage)
│   └── 宏观对冲
│       ├── 行业轮动 (Sector Rotation)
│       └── CTA 商品 (CTA Commodities)
└── 自定义策略 (Custom Strategies)
    └── 用户自定义策略（未来扩展）
```

---

## 2. 数据库设计

### 2.1 strategies 表

```sql
CREATE TABLE strategies (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL UNIQUE,
  category VARCHAR(32) NOT NULL COMMENT '均值回归/趋势跟踪/多因子/防御/波动率/宏观对冲',
  description TEXT COMMENT '策略描述',
  enabled BOOLEAN DEFAULT TRUE COMMENT '是否启用',
  is_builtin BOOLEAN DEFAULT TRUE COMMENT '是否内置策略',
  
  -- 策略参数（JSON存储）
  default_params JSON NOT NULL COMMENT '默认参数配置',
  current_params JSON COMMENT '当前参数配置（覆盖默认）',
  
  -- 信号源配置
  signal_sources JSON COMMENT '信号来源：["TECHNICAL","FUNDAMENTAL","SENTIMENT"]',
  
  -- 风险配置
  risk_profile JSON COMMENT '{"max_position_pct": 0.15, "stop_loss_pct": 0.02}',
  
  -- 运行配置
  run_schedule VARCHAR(64) COMMENT 'cron表达式：定时运行',
  auto_execute BOOLEAN DEFAULT FALSE COMMENT '是否自动执行信号',
  
  -- 性能统计（定期更新）
  win_rate DECIMAL(10, 4) DEFAULT 0,
  sharpe_ratio DECIMAL(10, 4) DEFAULT 0,
  total_signals INT DEFAULT 0,
  last_run_at DATETIME,
  
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  INDEX idx_category (category),
  INDEX idx_enabled (enabled)
);
```

### 2.2 strategy_runs 表（已存在，需优化）

```sql
ALTER TABLE strategy_runs ADD COLUMN strategy_category VARCHAR(32) AFTER strategy_id;
ALTER TABLE strategy_runs ADD COLUMN params_snapshot JSON COMMENT '运行时参数快照';
ALTER TABLE strategy_runs ADD INDEX idx_category_status (strategy_category, status);
```

### 2.3 trading_signals 表（已存在，需优化）

```sql
ALTER TABLE trading_signals ADD COLUMN strategy_category VARCHAR(32) AFTER strategy_id;
ALTER TABLE trading_signals ADD INDEX idx_strategy_category (strategy_category, created_at);
```

---

## 3. 策略详细设计

### 3.1 均值回归策略

#### A. 布林带均值回归 (Bollinger Bands Mean Reversion)

**策略逻辑**：
- 价格跌破下轨（-2σ）→ 做多
- 价格突破上轨（+2σ）→ 做空
- 价格回归中轨 → 平仓

**参数配置**：
```json
{
  "window": 20,              // 时间窗口（天）
  "std_multiplier": 2.0,     // 标准差倍数
  "stop_loss_pct": 0.02,     // 止损比例 2%
  "take_profit_pct": 0.03,   // 止盈比例 3%
  "max_position_pct": 0.15,  // 最大仓位 15%
  "min_volume": 1000000      // 最小成交量过滤
}
```

**信号生成规则**：
```python
def generate_signals(self, symbol: str, params: dict):
    # 1. 获取历史价格
    prices = await self.get_historical_prices(symbol, params['window'])
    
    # 2. 计算布林带
    sma = prices.rolling(params['window']).mean()
    std = prices.rolling(params['window']).std()
    upper_band = sma + params['std_multiplier'] * std
    lower_band = sma - params['std_multiplier'] * std
    
    current_price = prices.iloc[-1]
    
    # 3. 生成信号
    if current_price < lower_band.iloc[-1]:
        # 价格跌破下轨 → 做多
        return Signal(
            direction='LONG',
            entry_price=current_price,
            stop_loss=current_price * (1 - params['stop_loss_pct']),
            take_profit=sma.iloc[-1],  # 目标回归中轨
            signal_strength=abs((current_price - lower_band.iloc[-1]) / std.iloc[-1])
        )
    
    elif current_price > upper_band.iloc[-1]:
        # 价格突破上轨 → 做空
        return Signal(
            direction='SHORT',
            entry_price=current_price,
            stop_loss=current_price * (1 + params['stop_loss_pct']),
            take_profit=sma.iloc[-1],
            signal_strength=abs((current_price - upper_band.iloc[-1]) / std.iloc[-1])
        )
    
    return None
```

**适用场景**：
- 震荡市场
- 高流动性股票
- 避免在强趋势市使用

#### B. 配对交易 (Pairs Trading)

**策略逻辑**：
- 找到协整股票对（如 XLE vs CVX）
- 价差偏离均值 > 2σ → 开仓（买低卖高）
- 价差回归均值 → 平仓

**参数配置**：
```json
{
  "lookback_period": 90,      // 协整检验窗口（天）
  "cointegration_threshold": 0.05,  // p-value < 0.05
  "zscore_entry": 2.0,        // Z-score > 2 开仓
  "zscore_exit": 0.5,         // Z-score < 0.5 平仓
  "max_holding_days": 30,     // 最大持仓天数
  "pairs": [                  // 预设配对
    ["XLE", "CVX"],           // 能源ETF vs 雪佛龙
    ["XLF", "JPM"],           // 金融ETF vs 摩根大通
    ["QQQ", "AAPL"]           // 纳指ETF vs 苹果
  ]
}
```

**协整检验**：
```python
from statsmodels.tsa.stattools import coint

def check_cointegration(self, symbol1: str, symbol2: str, window: int):
    prices1 = await self.get_historical_prices(symbol1, window)
    prices2 = await self.get_historical_prices(symbol2, window)
    
    # Engle-Granger 协整检验
    score, pvalue, _ = coint(prices1, prices2)
    
    return pvalue < 0.05  # p-value < 0.05 说明协整
```

**信号生成**：
```python
def generate_pairs_signal(self, pair: tuple, params: dict):
    symbol1, symbol2 = pair
    
    # 1. 协整检验
    if not await self.check_cointegration(symbol1, symbol2, params['lookback_period']):
        return None
    
    # 2. 计算价差
    prices1 = await self.get_historical_prices(symbol1, params['lookback_period'])
    prices2 = await self.get_historical_prices(symbol2, params['lookback_period'])
    spread = prices1 - prices2
    
    # 3. 计算 Z-score
    zscore = (spread.iloc[-1] - spread.mean()) / spread.std()
    
    # 4. 生成信号
    if zscore > params['zscore_entry']:
        # 价差过高 → 卖symbol1 买symbol2
        return [
            Signal(symbol=symbol1, direction='SHORT', ...),
            Signal(symbol=symbol2, direction='LONG', ...)
        ]
    elif zscore < -params['zscore_entry']:
        # 价差过低 → 买symbol1 卖symbol2
        return [
            Signal(symbol=symbol1, direction='LONG', ...),
            Signal(symbol=symbol2, direction='SHORT', ...)
        ]
    
    return None
```

---

### 3.2 趋势跟踪策略

#### A. 突破动量 (Breakout Momentum)

**策略逻辑**：
- 突破 N 日高点 → 做多
- 跌破 N 日低点 → 做空/止损
- 结合成交量确认

**参数配置**：
```json
{
  "lookback_period": 20,      // 突破窗口（天）
  "volume_multiplier": 1.5,   // 成交量 > 均值1.5倍
  "atr_multiplier": 2.0,      // ATR止损倍数
  "max_position_pct": 0.20,   // 最大仓位 20%
  "min_breakout_pct": 0.02    // 最小突破幅度 2%
}
```

**信号生成**：
```python
def generate_breakout_signal(self, symbol: str, params: dict):
    prices = await self.get_historical_prices(symbol, params['lookback_period'])
    volumes = await self.get_historical_volumes(symbol, params['lookback_period'])
    
    high_n = prices.rolling(params['lookback_period']).max()
    low_n = prices.rolling(params['lookback_period']).min()
    
    current_price = prices.iloc[-1]
    current_volume = volumes.iloc[-1]
    avg_volume = volumes.rolling(20).mean().iloc[-1]
    
    # ATR 止损
    atr = self.calculate_atr(prices, 14)
    
    # 突破信号
    if (current_price > high_n.iloc[-2] and 
        current_volume > avg_volume * params['volume_multiplier'] and
        (current_price - high_n.iloc[-2]) / high_n.iloc[-2] > params['min_breakout_pct']):
        
        return Signal(
            direction='LONG',
            entry_price=current_price,
            stop_loss=current_price - atr * params['atr_multiplier'],
            signal_strength=current_volume / avg_volume
        )
    
    return None
```

#### B. 黄金交叉 (Golden Cross)

**策略逻辑**：
- MA50 上穿 MA200 → 做多
- MA50 下穿 MA200 → 做空/平多

**参数配置**：
```json
{
  "short_ma": 50,             // 短期均线
  "long_ma": 200,             // 长期均线
  "confirmation_days": 3,     // 确认天数
  "stop_loss_pct": 0.05,      // 止损 5%
  "max_position_pct": 0.25    // 最大仓位 25%
}
```

---

### 3.3 多因子策略

#### A. Fama-French 三因子

**策略逻辑**：
- 市场因子 (Rm - Rf)
- 规模因子 (SMB: Small Minus Big)
- 价值因子 (HML: High Minus Low)

**参数配置**：
```json
{
  "market_beta_min": 0.8,     // 市场Beta > 0.8
  "size_factor_min": -0.5,    // 小市值溢价
  "value_factor_min": 0.3,    // 价值溢价
  "rebalance_frequency": "monthly",
  "top_n_stocks": 20          // 选前20只
}
```

**因子计算**：
```python
def calculate_fama_french_factors(self, symbol: str):
    # 1. 市场因子
    market_return = await self.get_market_return('SPY')
    stock_return = await self.get_stock_return(symbol)
    market_factor = stock_return - market_return
    
    # 2. 规模因子 (市值)
    market_cap = await self.get_market_cap(symbol)
    size_factor = self.size_percentile(market_cap)
    
    # 3. 价值因子 (PB)
    pb_ratio = await self.get_pb_ratio(symbol)
    value_factor = self.value_percentile(pb_ratio)
    
    return {
        'market_factor': market_factor,
        'size_factor': size_factor,
        'value_factor': value_factor
    }
```

#### B. 动量+质量 (Momentum + Quality)

**策略逻辑**：
- 动量：过去 12 个月涨幅
- 质量：ROE > 15%，负债率 < 50%

**参数配置**：
```json
{
  "momentum_period": 252,     // 12个月动量
  "momentum_threshold": 0.20, // 涨幅 > 20%
  "roe_min": 0.15,            // ROE > 15%
  "debt_ratio_max": 0.50,     // 负债率 < 50%
  "top_n_stocks": 15
}
```

---

### 3.4 防御策略

#### A. 低波动率 (Low Volatility)

**策略逻辑**：
- 选择历史波动率最低的股票
- 市场下跌时相对稳定

**参数配置**：
```json
{
  "volatility_period": 60,    // 60日波动率
  "rebalance_frequency": "monthly",
  "top_n_stocks": 10,         // 选最低波动率前10只
  "max_position_pct": 0.10,   // 单标的最大10%
  "target_beta": 0.6          // 目标Beta < 0.6
}
```

**波动率计算**：
```python
def calculate_volatility(self, symbol: str, period: int):
    returns = await self.get_daily_returns(symbol, period)
    volatility = returns.std() * np.sqrt(252)  # 年化波动率
    return volatility
```

#### B. 尾部对冲 (Tail Hedge)

**策略逻辑**：
- 自动购买虚值看跌期权（OTM Put）
- 保护下跌风险

**参数配置**：
```json
{
  "hedge_ratio": 0.30,        // 对冲比例 30%
  "strike_otm_pct": 0.10,     // 虚值 10%
  "expiry_days": 30,          // 30天到期
  "vix_threshold": 20,        // VIX > 20 触发
  "max_cost_pct": 0.02        // 最大成本 2%
}
```

---

### 3.5 波动率策略

#### A. 铁鹰期权 (Iron Condor)

**策略逻辑**：
- 卖出跨式 + 保护腿
- 横盘市获利

**参数配置**：
```json
{
  "short_call_otm": 0.10,     // 卖出Call虚值10%
  "short_put_otm": 0.10,      // 卖出Put虚值10%
  "long_call_otm": 0.15,      // 保护Call虚值15%
  "long_put_otm": 0.15,       // 保护Put虚值15%
  "expiry_days": 30,
  "max_risk_pct": 0.05        // 最大风险5%
}
```

#### B. 波动率套利 (Volatility Arbitrage)

**策略逻辑**：
- 隐含波动率 vs 历史波动率
- IV > HV → 卖出期权
- IV < HV → 买入期权

**参数配置**：
```json
{
  "iv_hv_threshold": 0.20,    // IV - HV > 20%
  "lookback_period": 30,      // HV计算窗口
  "max_vega_exposure": 5000   // 最大Vega敞口
}
```

---

### 3.6 宏观对冲策略

#### A. 行业轮动 (Sector Rotation)

**策略逻辑**：
- 经济周期 → 行业表现轮动
- 早期复苏：科技、金融
- 中期扩张：工业、能源
- 晚期繁荣：消费、医疗
- 衰退：公用事业、必需消费

**参数配置**：
```json
{
  "sectors": [
    "XLK",  // 科技
    "XLF",  // 金融
    "XLI",  // 工业
    "XLE",  // 能源
    "XLY",  // 可选消费
    "XLV",  // 医疗
    "XLP",  // 必需消费
    "XLU"   // 公用事业
  ],
  "rebalance_frequency": "monthly",
  "momentum_period": 60,      // 60日相对强度
  "top_n_sectors": 3          // 选前3强行业
}
```

**经济周期判断**：
```python
def detect_economic_cycle(self):
    # 宏观指标
    gdp_growth = await self.get_fred_data('GDP')
    unemployment = await self.get_fred_data('UNRATE')
    yield_curve = await self.get_fred_data('T10Y2Y')  # 10Y-2Y国债利差
    
    if gdp_growth > 2.5 and unemployment < 4.5:
        return 'EXPANSION'  # 扩张期
    elif yield_curve < 0:
        return 'RECESSION'  # 衰退期
    else:
        return 'RECOVERY'   # 复苏期
```

#### B. CTA 商品 (CTA Commodities)

**策略逻辑**：
- 商品期货趋势跟踪
- 黄金、原油、天然气

**参数配置**：
```json
{
  "commodities": ["GLD", "USO", "UNG"],
  "trend_period": 50,         // 50日趋势
  "breakout_period": 20,      // 20日突破
  "atr_multiplier": 2.5,      // ATR止损
  "max_position_pct": 0.15
}
```

---

## 4. 策略引擎实现

### 4.1 StrategyService - 策略服务

```python
# app/services/strategy_service.py
from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.trading_signal import Strategy, StrategyRun, TradingSignal

class StrategyService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_all_strategies(self, category: Optional[str] = None) -> List[Strategy]:
        """获取策略列表"""
        query = select(Strategy).where(Strategy.is_builtin == True)
        if category:
            query = query.where(Strategy.category == category)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_strategy_detail(self, strategy_id: int) -> Strategy:
        """获取策略详情"""
        result = await self.db.execute(
            select(Strategy).where(Strategy.id == strategy_id)
        )
        return result.scalar_one_or_none()
    
    async def run_strategy(self, strategy_id: int, account_id: str) -> StrategyRun:
        """运行策略"""
        strategy = await self.get_strategy_detail(strategy_id)
        
        # 创建策略运行记录
        run = StrategyRun(
            strategy_id=strategy_id,
            strategy_category=strategy.category,
            account_id=account_id,
            params_snapshot=strategy.current_params or strategy.default_params,
            status='RUNNING'
        )
        self.db.add(run)
        await self.db.commit()
        
        # 执行策略逻辑
        try:
            signals = await self._execute_strategy_logic(strategy, run.params_snapshot)
            
            # 保存信号
            for signal_data in signals:
                signal = TradingSignal(
                    strategy_id=strategy_id,
                    strategy_category=strategy.category,
                    strategy_run_id=run.id,
                    account_id=account_id,
                    **signal_data
                )
                self.db.add(signal)
            
            run.status = 'COMPLETED'
            run.signal_count = len(signals)
            
        except Exception as e:
            run.status = 'FAILED'
            run.error_message = str(e)
        
        await self.db.commit()
        return run
    
    async def _execute_strategy_logic(self, strategy: Strategy, params: dict) -> List[Dict]:
        """执行策略逻辑（根据类别调用不同实现）"""
        if strategy.category == '均值回归':
            if '布林带' in strategy.name:
                return await self._bollinger_bands_strategy(params)
            elif '配对交易' in strategy.name:
                return await self._pairs_trading_strategy(params)
        
        elif strategy.category == '趋势跟踪':
            if '突破动量' in strategy.name:
                return await self._breakout_momentum_strategy(params)
            elif '黄金交叉' in strategy.name:
                return await self._golden_cross_strategy(params)
        
        # ... 其他策略实现
        
        return []
    
    async def update_strategy_params(self, strategy_id: int, params: dict):
        """更新策略参数"""
        strategy = await self.get_strategy_detail(strategy_id)
        strategy.current_params = params
        await self.db.commit()
    
    async def toggle_strategy(self, strategy_id: int) -> bool:
        """启用/禁用策略"""
        strategy = await self.get_strategy_detail(strategy_id)
        strategy.enabled = not strategy.enabled
        await self.db.commit()
        return strategy.enabled
    
    async def get_strategy_performance(self, strategy_id: int) -> Dict:
        """获取策略历史表现"""
        # 查询该策略所有历史信号
        result = await self.db.execute(
            select(TradingSignal)
            .where(TradingSignal.strategy_id == strategy_id)
            .where(TradingSignal.signal_status == 'EXECUTED')
        )
        signals = result.scalars().all()
        
        # 计算胜率、盈亏比、Sharpe等
        if not signals:
            return {}
        
        wins = [s for s in signals if s.pnl and s.pnl > 0]
        win_rate = len(wins) / len(signals) * 100
        
        avg_win = sum(s.pnl for s in wins) / len(wins) if wins else 0
        losses = [s for s in signals if s.pnl and s.pnl < 0]
        avg_loss = abs(sum(s.pnl for s in losses) / len(losses)) if losses else 1
        
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        
        return {
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_signals': len(signals),
            'total_pnl': sum(s.pnl for s in signals if s.pnl),
            'avg_holding_days': ...,  # 计算平均持仓天数
            'sharpe_ratio': ...       # 计算Sharpe
        }
```

### 4.2 策略实现示例

```python
# app/strategies/mean_reversion/bollinger_bands.py
import numpy as np
import pandas as pd
from typing import List, Dict

class BollingerBandsMeanReversion:
    """布林带均值回归策略"""
    
    async def generate_signals(self, params: dict) -> List[Dict]:
        """生成交易信号"""
        signals = []
        
        # 获取股票池
        symbols = await self._get_stock_universe(params)
        
        for symbol in symbols:
            try:
                signal = await self._analyze_symbol(symbol, params)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"分析 {symbol} 失败: {e}")
        
        return signals
    
    async def _analyze_symbol(self, symbol: str, params: dict) -> Optional[Dict]:
        """分析单个标的"""
        # 1. 获取历史数据
        prices = await self.market_data_service.get_historical_prices(
            symbol, 
            days=params['window'] + 10
        )
        
        if len(prices) < params['window']:
            return None
        
        # 2. 计算布林带
        df = pd.DataFrame({'price': prices})
        df['sma'] = df['price'].rolling(params['window']).mean()
        df['std'] = df['price'].rolling(params['window']).std()
        df['upper'] = df['sma'] + params['std_multiplier'] * df['std']
        df['lower'] = df['sma'] - params['std_multiplier'] * df['std']
        
        current_price = df['price'].iloc[-1]
        sma = df['sma'].iloc[-1]
        upper = df['upper'].iloc[-1]
        lower = df['lower'].iloc[-1]
        std = df['std'].iloc[-1]
        
        # 3. 生成信号
        if current_price < lower:
            # 做多信号
            signal_strength = abs((current_price - lower) / std)
            
            return {
                'symbol': symbol,
                'direction': 'LONG',
                'entry_price': current_price,
                'stop_loss': current_price * (1 - params['stop_loss_pct']),
                'take_profit': sma,  # 目标回归中轨
                'signal_strength': min(signal_strength, 1.0),
                'signal_metadata': {
                    'upper_band': upper,
                    'lower_band': lower,
                    'sma': sma,
                    'deviation': (current_price - sma) / std
                }
            }
        
        elif current_price > upper:
            # 做空信号（如果允许）
            signal_strength = abs((current_price - upper) / std)
            
            return {
                'symbol': symbol,
                'direction': 'SHORT',
                'entry_price': current_price,
                'stop_loss': current_price * (1 + params['stop_loss_pct']),
                'take_profit': sma,
                'signal_strength': min(signal_strength, 1.0),
                'signal_metadata': {
                    'upper_band': upper,
                    'lower_band': lower,
                    'sma': sma,
                    'deviation': (current_price - sma) / std
                }
            }
        
        return None
    
    async def _get_stock_universe(self, params: dict) -> List[str]:
        """获取股票池"""
        # 可以从配置文件读取，或动态生成
        # 示例：标普500成分股
        return ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', ...]  # 简化
```

---

## 5. API 端点设计

### 5.1 策略管理端点

```python
# app/routers/strategies.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.strategy_service import StrategyService

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

@router.get("/")
async def get_strategies(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取策略列表"""
    service = StrategyService(db)
    strategies = await service.get_all_strategies(category)
    return strategies

@router.get("/{strategy_id}")
async def get_strategy_detail(
    strategy_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取策略详情"""
    service = StrategyService(db)
    strategy = await service.get_strategy_detail(strategy_id)
    if not strategy:
        raise HTTPException(404, "策略不存在")
    return strategy

@router.post("/{strategy_id}/run")
async def run_strategy(
    strategy_id: int,
    account_id: str = Depends(get_current_account),
    db: AsyncSession = Depends(get_db)
):
    """运行策略"""
    service = StrategyService(db)
    run = await service.run_strategy(strategy_id, account_id)
    return run

@router.put("/{strategy_id}/params")
async def update_strategy_params(
    strategy_id: int,
    params: dict,
    db: AsyncSession = Depends(get_db)
):
    """更新策略参数"""
    service = StrategyService(db)
    await service.update_strategy_params(strategy_id, params)
    return {"message": "参数更新成功"}

@router.put("/{strategy_id}/toggle")
async def toggle_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db)
):
    """启用/禁用策略"""
    service = StrategyService(db)
    enabled = await service.toggle_strategy(strategy_id)
    return {"enabled": enabled}

@router.get("/{strategy_id}/performance")
async def get_strategy_performance(
    strategy_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取策略历史表现"""
    service = StrategyService(db)
    performance = await service.get_strategy_performance(strategy_id)
    return performance

@router.get("/{strategy_id}/signals")
async def get_strategy_signals(
    strategy_id: int,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """获取策略最近信号"""
    result = await db.execute(
        select(TradingSignal)
        .where(TradingSignal.strategy_id == strategy_id)
        .order_by(TradingSignal.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
```

---

## 6. 初始化脚本

### 6.1 初始化12个内置策略

```python
# scripts/init_strategies.py
import asyncio
from app.models.db import async_session
from app.models.trading_signal import Strategy

strategies_data = [
    # 均值回归
    {
        'name': '布林带均值回归',
        'category': '均值回归',
        'description': '基于布林带指标，当价格偏离中轨超逾2倍标准差时触发均值回归交易信号。适用于震荡市。',
        'default_params': {
            'window': 20,
            'std_multiplier': 2.0,
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.03,
            'max_position_pct': 0.15,
            'min_volume': 1000000
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.15,
            'stop_loss_pct': 0.02,
            'risk_level': 'MEDIUM'
        },
        'enabled': True
    },
    {
        'name': '配对交易',
        'category': '均值回归',
        'description': '协整股票对价差交易，价差偏离均值时开仓，回归时平仓。',
        'default_params': {
            'lookback_period': 90,
            'cointegration_threshold': 0.05,
            'zscore_entry': 2.0,
            'zscore_exit': 0.5,
            'max_holding_days': 30,
            'pairs': [['XLE', 'CVX'], ['XLF', 'JPM'], ['QQQ', 'AAPL']]
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.20,
            'stop_loss_pct': 0.03,
            'risk_level': 'MEDIUM'
        },
        'enabled': False  # 默认禁用
    },
    
    # 趋势跟踪
    {
        'name': '突破动量',
        'category': '趋势跟踪',
        'description': '突破关键阻力/支撑位加仓，结合成交量确认。',
        'default_params': {
            'lookback_period': 20,
            'volume_multiplier': 1.5,
            'atr_multiplier': 2.0,
            'max_position_pct': 0.20,
            'min_breakout_pct': 0.02
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.20,
            'stop_loss_pct': 0.05,
            'risk_level': 'MEDIUM'
        },
        'enabled': True
    },
    {
        'name': '黄金交叉',
        'category': '趋势跟踪',
        'description': 'MA50上穿MA200做多，下穿平多。经典趋势跟踪。',
        'default_params': {
            'short_ma': 50,
            'long_ma': 200,
            'confirmation_days': 3,
            'stop_loss_pct': 0.05,
            'max_position_pct': 0.25
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.25,
            'stop_loss_pct': 0.05,
            'risk_level': 'MEDIUM'
        },
        'enabled': True
    },
    
    # 多因子
    {
        'name': 'Fama-French三因子',
        'category': '多因子',
        'description': '市场/规模/价值三因子选股，学术派经典策略。',
        'default_params': {
            'market_beta_min': 0.8,
            'size_factor_min': -0.5,
            'value_factor_min': 0.3,
            'rebalance_frequency': 'monthly',
            'top_n_stocks': 20
        },
        'signal_sources': ['FUNDAMENTAL', 'TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.10,
            'stop_loss_pct': 0.10,
            'risk_level': 'LOW'
        },
        'enabled': True
    },
    {
        'name': '动量+质量',
        'category': '多因子',
        'description': '动量（12月涨幅）+ 质量（ROE>15%），双因子增强。',
        'default_params': {
            'momentum_period': 252,
            'momentum_threshold': 0.20,
            'roe_min': 0.15,
            'debt_ratio_max': 0.50,
            'top_n_stocks': 15
        },
        'signal_sources': ['FUNDAMENTAL', 'TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.12,
            'stop_loss_pct': 0.08,
            'risk_level': 'MEDIUM'
        },
        'enabled': True
    },
    
    # 防御策略
    {
        'name': '低波动率',
        'category': '防御',
        'description': '选择历史波动率最低的股票，熊市防御利器。',
        'default_params': {
            'volatility_period': 60,
            'rebalance_frequency': 'monthly',
            'top_n_stocks': 10,
            'max_position_pct': 0.10,
            'target_beta': 0.6
        },
        'signal_sources': ['TECHNICAL', 'FUNDAMENTAL'],
        'risk_profile': {
            'max_position_pct': 0.10,
            'stop_loss_pct': 0.08,
            'risk_level': 'LOW'
        },
        'enabled': True
    },
    {
        'name': '尾部对冲',
        'category': '防御',
        'description': '自动购买虚值看跌期权，保护下跌风险。',
        'default_params': {
            'hedge_ratio': 0.30,
            'strike_otm_pct': 0.10,
            'expiry_days': 30,
            'vix_threshold': 20,
            'max_cost_pct': 0.02
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.30,
            'stop_loss_pct': 1.00,  # 期权最大损失100%
            'risk_level': 'LOW'
        },
        'enabled': False  # 谨慎启用
    },
    
    # 波动率策略
    {
        'name': '铁鹰期权',
        'category': '波动率',
        'description': '卖出跨式+保护腿，横盘市获利。',
        'default_params': {
            'short_call_otm': 0.10,
            'short_put_otm': 0.10,
            'long_call_otm': 0.15,
            'long_put_otm': 0.15,
            'expiry_days': 30,
            'max_risk_pct': 0.05
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.15,
            'stop_loss_pct': 0.50,
            'risk_level': 'HIGH'
        },
        'enabled': False  # 高级策略
    },
    {
        'name': '波动率套利',
        'category': '波动率',
        'description': '隐含波动率vs历史波动率套利，IV>HV卖出。',
        'default_params': {
            'iv_hv_threshold': 0.20,
            'lookback_period': 30,
            'max_vega_exposure': 5000
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.20,
            'stop_loss_pct': 0.30,
            'risk_level': 'HIGH'
        },
        'enabled': False
    },
    
    # 宏观对冲
    {
        'name': '行业轮动',
        'category': '宏观对冲',
        'description': '经济周期驱动的行业轮动，复苏-扩张-衰退配置。',
        'default_params': {
            'sectors': ['XLK', 'XLF', 'XLI', 'XLE', 'XLY', 'XLV', 'XLP', 'XLU'],
            'rebalance_frequency': 'monthly',
            'momentum_period': 60,
            'top_n_sectors': 3
        },
        'signal_sources': ['FUNDAMENTAL', 'TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.33,
            'stop_loss_pct': 0.10,
            'risk_level': 'MEDIUM'
        },
        'enabled': True
    },
    {
        'name': 'CTA商品',
        'category': '宏观对冲',
        'description': '商品期货趋势跟踪，黄金/原油/天然气。',
        'default_params': {
            'commodities': ['GLD', 'USO', 'UNG'],
            'trend_period': 50,
            'breakout_period': 20,
            'atr_multiplier': 2.5,
            'max_position_pct': 0.15
        },
        'signal_sources': ['TECHNICAL'],
        'risk_profile': {
            'max_position_pct': 0.15,
            'stop_loss_pct': 0.05,
            'risk_level': 'MEDIUM'
        },
        'enabled': True
    }
]

async def init_strategies():
    async with async_session() as session:
        for data in strategies_data:
            strategy = Strategy(**data)
            session.add(strategy)
        
        await session.commit()
        print(f"✅ 初始化 {len(strategies_data)} 个内置策略完成")

if __name__ == "__main__":
    asyncio.run(init_strategies())
```

---

## 7. 部署与运维

### 7.1 定时运行

使用 APScheduler 定时运行已启用的策略：

```python
# app/jobs/strategy_jobs.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=9, minute=30, id='run_enabled_strategies')
async def run_enabled_strategies_job():
    """每日盘前运行已启用策略"""
    async with async_session() as db:
        service = StrategyService(db)
        strategies = await service.get_all_strategies()
        
        for strategy in strategies:
            if strategy.enabled:
                try:
                    await service.run_strategy(strategy.id, account_id='SYSTEM')
                    logger.info(f"✅ 策略 {strategy.name} 运行成功")
                except Exception as e:
                    logger.error(f"❌ 策略 {strategy.name} 运行失败: {e}")
```

### 7.2 性能监控

定期更新策略表现统计：

```python
@scheduler.scheduled_job('cron', hour=0, minute=0, id='update_strategy_performance')
async def update_strategy_performance_job():
    """每日凌晨更新策略表现"""
    async with async_session() as db:
        service = StrategyService(db)
        strategies = await service.get_all_strategies()
        
        for strategy in strategies:
            performance = await service.get_strategy_performance(strategy.id)
            
            # 更新策略表
            strategy.win_rate = performance.get('win_rate', 0)
            strategy.sharpe_ratio = performance.get('sharpe_ratio', 0)
            strategy.total_signals = performance.get('total_signals', 0)
            strategy.last_run_at = datetime.now()
        
        await db.commit()
```

---

## 8. 参考资料

### 8.1 理论基础

- **Fama-French 三因子模型**：《Common risk factors in the returns on stocks and bonds》(1993)
- **配对交易**：Gatev et al. 《Pairs Trading: Performance of a Relative-Value Arbitrage Rule》(2006)
- **低波动率异象**：Ang et al. 《The Cross-Section of Volatility and Expected Returns》(2006)

### 8.2 实践参考

- **BlackRock** - Systematic Active Equity
- **AQR** - Style Premia
- **Bridgewater** - All Weather Portfolio
- **Renaissance Technologies** - Medallion Fund (公开信息)

---

## 附录

### A. 策略矩阵

| 市场环境 | 推荐策略 | 风险等级 |
|----------|----------|----------|
| 牛市 | 突破动量、黄金交叉、动量+质量 | MEDIUM |
| 熊市 | 低波动率、尾部对冲 | LOW |
| 震荡市 | 布林带均值回归、铁鹰期权 | MEDIUM |
| 高波动 | 波动率套利、配对交易 | HIGH |
| 危机 | 尾部对冲、行业轮动（防御） | LOW |

### B. 回测要求

所有新策略上线前需完成：
- 至少 3 年历史回测
- Sharpe Ratio > 1.0
- 最大回撤 < 20%
- 月度胜率 > 50%

### C. 风控要求

- 单策略最大仓位：25%
- 单标的最大仓位：15%
- 日内最大亏损：-3%
- 触发强制平仓：-5%
