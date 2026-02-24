# 后端架构设计文档

> **AI量化交易闭环系统** - Backend Design  
> 版本：V10.0 | 更新日期：2026-02-24
> 
> **V10 变更摘要**：AI 自主决策引擎（三级自主模式）、DataHub 多源路由、BacktestEngine（Walk-Forward）、PortfolioOptimizer（Markowitz+Kelly）、RiskGate 风险门、压力测试服务、TWAP/VWAP 执行算法、Trading Copilot、Paper Trading、期权分析中心（只读）、AI 周报服务、6 张新增 DB 表

---

## 1. 架构概览

### 1.1 技术栈

- **框架**：FastAPI 0.109+ (ASGI)
- **数据库**：MySQL 8.0 + SQLAlchemy 2.0 (Async)
- **缓存**：Redis 7.0
- **调度器**：APScheduler
- **券商接口**：Tiger Trade API
- **AI**：OpenAI（gpt-4o-mini / gpt-5.2）+ DeepSeek（deepseek-chat / deepseek-reasoner）
- **数据源**：yfinance (主) + FRED (宏观) + Tiger (实时报价) — DataHub 多源路由

### 1.2 AI 模型路由策略

| 场景 | 轻量（默认） | 复杂推理 |
|------|-------------|---------|
| Copilot 对话 | deepseek-chat / gpt-4o-mini | deepseek-reasoner / gpt-5.2 |
| 自主决策引擎 | — | deepseek-reasoner / gpt-5.2 |
| 周报/深度分析 | — | deepseek-reasoner / gpt-5.2 |
| 信号简单摘要 | deepseek-chat / gpt-4o-mini | — |

路由逻辑：`AI_LIGHTWEIGHT_MODEL` / `AI_COMPLEX_MODEL` 从 config 读取；客户端统一使用 `BaseAIClient`。

### 1.3 项目结构

```
├── app/
│   ├── main.py                       # FastAPI 应用入口（V10: 注册 24 个路由组）
│   ├── core/
│   │   ├── config.py                 # 新增 12 个 V10 配置项
│   │   ├── security.py               # JWT + bcrypt
│   │   └── dependencies.py           # 依赖注入
│   │
│   ├── data/
│   │   └── hub.py                    # V10 新增：DataHub 多源路由
│   │
│   ├── models/                       # SQLAlchemy 数据模型 (21+ 表)
│   │   ├── ...（原有 15 张表）
│   │   ├── backtest_task.py          # V10 新增
│   │   ├── portfolio_snapshot.py     # V10 新增
│   │   ├── paper_account.py          # V10 新增
│   │   ├── copilot_message.py        # V10 新增
│   │   ├── algo_execution_task.py    # V10 新增
│   │   └── autonomy_audit_log.py     # V10 新增
│   │
│   ├── schemas/                      # Pydantic 响应模型
│   │   └── ...（原有 + 8 组新增）
│   │
│   ├── services/                     # 业务逻辑层 (28+ 服务)
│   │   ├── ...（原有 20 个服务）
│   │   ├── risk_gate_service.py      # V10 新增：非绕过 VaR+压测门
│   │   ├── autonomous_engine.py      # V10 新增：三级自主决策引擎
│   │   ├── stress_test_service.py    # V10 新增
│   │   ├── twap_vwap_service.py      # V10 新增：执行算法
│   │   ├── copilot_service.py        # V10 新增：对话式接口
│   │   ├── options_analysis_service.py # V10 新增（只读）
│   │   ├── paper_trading_service.py  # V10 新增
│   │   └── weekly_report_service.py  # V10 新增
│   │
│   ├── engine/                       # 核心引擎
│   │   ├── signal_engine.py
│   │   ├── order_executor.py
│   │   ├── performance_analyzer.py
│   │   ├── adaptive_optimizer.py
│   │   ├── quant_trading_loop.py
│   │   ├── auto_hedge_engine.py
│   │   ├── alert_engine.py
│   │   ├── backtest/                 # V10 新增
│   │   │   ├── __init__.py
│   │   │   └── runner.py             # 事件驱动回测 + Walk-Forward
│   │   └── portfolio/               # V10 新增
│   │       └── optimizer.py          # Markowitz + Kelly
│   │
│   ├── routers/                      # API 路由层 (24 个端点组)
│   │   ├── ...（原有 16 个路由）
│   │   ├── autonomy.py               # V10 新增
│   │   ├── copilot.py                # V10 新增
│   │   ├── backtest.py               # V10 新增
│   │   ├── portfolio.py              # V10 新增
│   │   ├── stress_test.py            # V10 新增
│   │   ├── paper_trading.py          # V10 新增
│   │   ├── options_analysis.py       # V10 新增
│   │   └── execution_algo.py         # V10 新增
│   │
│   ├── broker/
│   ├── jobs/
│   └── utils/
│
├── tests/
├── requirements.txt
└── .env
```

---

## 2. 数据库设计

### 2.1 核心表结构（新增8张表 + 优化已有表）

#### A. strategies - 策略库

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
  signal_sources JSON COMMENT '["TECHNICAL","FUNDAMENTAL","SENTIMENT"]',
  
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

**用途**：策略库管理，存储12大类量化策略配置。

> **详细设计参考**：`docs/STRATEGY_LIBRARY_DESIGN.md` - 12个策略完整技术规范

#### B. equity_snapshots - 账户权益快照

```sql
CREATE TABLE equity_snapshots (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  snapshot_date DATE NOT NULL,
  total_equity DECIMAL(20, 2) NOT NULL,
  cash DECIMAL(20, 2) DEFAULT 0,
  market_value DECIMAL(20, 2) DEFAULT 0,
  realized_pnl DECIMAL(20, 2) DEFAULT 0,
  unrealized_pnl DECIMAL(20, 2) DEFAULT 0,
  daily_return DECIMAL(10, 6) DEFAULT NULL,
  cumulative_return DECIMAL(10, 6) DEFAULT NULL,
  max_drawdown_pct DECIMAL(10, 6) DEFAULT NULL,
  benchmark_return DECIMAL(10, 6) DEFAULT NULL COMMENT 'SPY daily return',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_account_date (account_id, snapshot_date),
  INDEX idx_account_date (account_id, snapshot_date)
);
```

**用途**：每日账户权益快照，用于资金曲线绘制和收益分析。

#### B. trade_journal - 交易日志

```sql
CREATE TABLE trade_journal (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  direction VARCHAR(8) NOT NULL,
  entry_date DATE,
  exit_date DATE,
  entry_price DECIMAL(20, 6),
  exit_price DECIMAL(20, 6),
  quantity DECIMAL(20, 6),
  realized_pnl DECIMAL(20, 2),
  plan_id INT,
  execution_quality INT COMMENT '1-5 自评',
  emotion_state VARCHAR(16) COMMENT 'calm/anxious/revenge/fomo/greedy',
  mistake_tags JSON COMMENT '["sell_fly","chase_high"]',
  lesson_learned TEXT,
  ai_review TEXT,
  journal_status VARCHAR(16) DEFAULT 'DRAFT' COMMENT 'DRAFT/COMPLETED/REVIEWED',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_account_date (account_id, entry_date)
);
```

**用途**：记录每笔交易的完整生命周期，支持复盘和 AI 评审。

#### C. price_alerts - 价格告警

```sql
CREATE TABLE price_alerts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  alert_type VARCHAR(16) NOT NULL COMMENT 'PRICE_ABOVE/PRICE_BELOW/PERCENT_CHANGE',
  threshold_value DECIMAL(20, 6) NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  triggered_at DATETIME,
  trigger_count INT DEFAULT 0,
  action_type VARCHAR(16) COMMENT 'NOTIFY_ONLY/CREATE_PLAN/AUTO_TRADE',
  action_params JSON,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_symbol_active (symbol, is_active)
);
```

**用途**：价格条件触发告警，支持多种响应动作。

#### D. ai_evaluation_history - AI 评估历史

```sql
CREATE TABLE ai_evaluation_history (
  id INT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  current_price DECIMAL(20, 6),
  direction VARCHAR(16),
  confidence INT,
  action VARCHAR(16),
  entry_price DECIMAL(20, 6),
  stop_loss DECIMAL(20, 6),
  take_profit DECIMAL(20, 6),
  position_pct DECIMAL(10, 4),
  risk_level VARCHAR(16),
  reasoning TEXT,
  key_factors JSON,
  risk_reward_ratio VARCHAR(16),
  scenarios JSON,
  catalysts JSON,
  holding_period VARCHAR(64),
  dimensions JSON COMMENT '技术面/基本面/K线分析详情',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_account_symbol (account_id, symbol),
  INDEX idx_eval_symbol (symbol),
  INDEX idx_eval_created (created_at)
);
```

**用途**：存储 AI 评估结果，按标的覆盖更新（同一标的只保留最新评估）。

#### E. trading_signals - 交易信号

```sql
CREATE TABLE trading_signals (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  strategy_id INT NOT NULL,
  strategy_run_id BIGINT,
  symbol VARCHAR(32) NOT NULL,
  direction VARCHAR(8) NOT NULL,
  signal_strength DECIMAL(10, 4),
  weight DECIMAL(10, 6),
  risk_score DECIMAL(10, 4),
  entry_price DECIMAL(20, 6),
  stop_loss DECIMAL(20, 6),
  take_profit DECIMAL(20, 6),
  position_size DECIMAL(20, 6),
  signal_metadata JSON,
  signal_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  validation_errors JSON,
  execution_plan_id INT,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  expires_at DATETIME,
  executed_at DATETIME,
  INDEX idx_account_status (account_id, signal_status),
  INDEX idx_strategy (strategy_id, created_at)
);
```

**用途**：策略运行生成的交易信号，支持批量执行和状态跟踪。

#### F. trading_plans - 交易计划

```sql
CREATE TABLE trading_plans (
  id INT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  direction VARCHAR(8) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  entry_price DECIMAL(20, 6),
  stop_loss DECIMAL(20, 6),
  take_profit DECIMAL(20, 6),
  quantity DECIMAL(20, 6),
  plan_type VARCHAR(16),
  created_source VARCHAR(32),
  reasoning TEXT,
  auto_execute BOOLEAN DEFAULT FALSE,
  expired_at DATETIME,
  is_deleted BOOLEAN DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_account_status (account_id, status)
);
```

**用途**：交易计划管理，支持自动执行和生命周期跟踪。

#### G. audit_logs - 操作审计

```sql
CREATE TABLE audit_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  action_type VARCHAR(32) NOT NULL,
  resource_type VARCHAR(32),
  resource_id VARCHAR(64),
  details JSON,
  ip_address VARCHAR(45),
  user_agent TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_time (account_id, created_at)
);
```

**用途**：记录关键操作（订单/计划/风控调整），用于安全审计。

### 2.2 V10 新增表

#### G. backtest_tasks - 回测任务

```sql
CREATE TABLE backtest_tasks (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  strategy_name VARCHAR(128) NOT NULL,
  symbols JSON NOT NULL COMMENT '["AAPL","NVDA"]',
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  initial_capital DECIMAL(20,2) NOT NULL DEFAULT 100000,
  walk_forward BOOLEAN DEFAULT FALSE,
  status VARCHAR(16) DEFAULT 'PENDING' COMMENT 'PENDING/RUNNING/DONE/FAILED',
  result JSON COMMENT '{"annualized_return":0.18,"sharpe":1.42,"max_drawdown":-0.083,"win_rate":0.62}',
  error_msg TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME,
  INDEX idx_account_status (account_id, status)
);
```

#### H. portfolio_snapshots - 组合优化快照

```sql
CREATE TABLE portfolio_snapshots (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  method VARCHAR(32) NOT NULL COMMENT 'MARKOWITZ/RISK_PARITY/KELLY',
  current_weights JSON NOT NULL,
  target_weights JSON NOT NULL,
  frontier_data JSON COMMENT '有效前沿散点数据',
  expected_return DECIMAL(10,6),
  expected_volatility DECIMAL(10,6),
  sharpe_ratio DECIMAL(10,4),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_time (account_id, created_at)
);
```

#### I. paper_accounts - 模拟账户

```sql
CREATE TABLE paper_accounts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL UNIQUE,
  initial_capital DECIMAL(20,2) NOT NULL DEFAULT 100000,
  current_equity DECIMAL(20,2) NOT NULL,
  realized_pnl DECIMAL(20,2) DEFAULT 0,
  unrealized_pnl DECIMAL(20,2) DEFAULT 0,
  positions JSON COMMENT '当前模拟持仓',
  trade_log JSON COMMENT '历史成交记录（最近 500 条）',
  reset_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

#### J. copilot_messages - Copilot 对话记录

```sql
CREATE TABLE copilot_messages (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  session_id VARCHAR(64) NOT NULL,
  role VARCHAR(8) NOT NULL COMMENT 'user/assistant',
  content TEXT NOT NULL,
  model_used VARCHAR(64),
  action_intent JSON COMMENT '{"type":"modify_stop","params":{"symbol":"AAPL","stop":175}}',
  action_confirmed BOOLEAN DEFAULT NULL,
  tokens_used INT DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_session (account_id, session_id),
  INDEX idx_created (created_at)
);
```

#### K. algo_execution_tasks - 算法执行任务（TWAP/VWAP）

```sql
CREATE TABLE algo_execution_tasks (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  side VARCHAR(4) NOT NULL COMMENT 'BUY/SELL',
  algo VARCHAR(8) NOT NULL COMMENT 'TWAP/VWAP/MKT',
  total_qty DECIMAL(20,6) NOT NULL,
  filled_qty DECIMAL(20,6) DEFAULT 0,
  avg_price DECIMAL(20,6) DEFAULT 0,
  slices INT DEFAULT 10,
  interval_secs INT DEFAULT 60,
  status VARCHAR(16) DEFAULT 'PENDING' COMMENT 'PENDING/RUNNING/DONE/CANCELLED',
  slices_log JSON COMMENT '每片执行记录',
  started_at DATETIME,
  completed_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_status (account_id, status)
);
```

#### L. autonomy_audit_log - AI 自主审计日志

```sql
CREATE TABLE autonomy_audit_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  autonomy_level VARCHAR(16) NOT NULL COMMENT 'FULL/SEMI/ADVISORY',
  decision_type VARCHAR(32) NOT NULL COMMENT 'BUY/SELL/HOLD/REBALANCE/REJECT',
  symbol VARCHAR(32),
  ai_reasoning TEXT COMMENT 'AI 决策推理',
  confidence_score DECIMAL(5,2),
  risk_gate_passed BOOLEAN NOT NULL,
  risk_gate_detail JSON,
  order_id VARCHAR(64) COMMENT '实际下单 order_id / paper_trade_id',
  revoked_at DATETIME,
  revoke_reason TEXT,
  circuit_breaker_triggered BOOLEAN DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_time (account_id, created_at),
  INDEX idx_decision_type (decision_type)
);
```

---

## 3. 核心引擎设计

### 3.1 StrategyEngine - 策略引擎

**职责**：管理12大类量化策略，执行策略逻辑生成交易信号。

**策略分类**：
- **均值回归** (Mean Reversion): 布林带均值回归、配对交易
- **趋势跟踪** (Trend Following): 突破动量、黄金交叉
- **多因子** (Multi-Factor): Fama-French三因子、动量+质量
- **防御策略** (Defensive): 低波动率、尾部对冲
- **波动率** (Volatility): 铁鹰期权、波动率套利
- **宏观对冲** (Macro Hedge): 行业轮动、CTA商品

**关键方法**：
- `get_all_strategies()` - 获取策略列表
- `run_strategy(strategy_id)` - 运行指定策略
- `update_strategy_params()` - 更新策略参数
- `toggle_strategy()` - 启用/禁用策略
- `get_strategy_performance()` - 获取历史表现

**策略运行流程**：
```python
async def run_strategy(strategy_id: int, account_id: str):
    # 1. 加载策略配置
    strategy = await self.load_strategy(strategy_id)
    
    # 2. 创建策略运行记录
    run = StrategyRun(strategy_id=strategy_id, status='RUNNING')
    
    # 3. 执行策略逻辑（根据类别调用不同实现）
    signals = await self._execute_strategy_logic(strategy)
    
    # 4. 保存交易信号
    for signal_data in signals:
        signal = TradingSignal(strategy_id=strategy_id, **signal_data)
        await self.save_signal(signal)
    
    # 5. 更新运行状态
    run.status = 'COMPLETED'
    run.signal_count = len(signals)
    
    return run
```

**详细设计**：参见 `docs/STRATEGY_LIBRARY_DESIGN.md`

### 3.2 SignalEngine - 信号引擎

**职责**：从策略运行结果生成交易信号，统一评分和验证。

**关键方法**：
- `generate_signals_from_strategy_run()` - 生成信号
- `validate_signal()` - 风险检查
- `get_pending_signals()` - 获取待执行信号
- `update_signal_execution()` - 更新执行状态
- `evaluate_signal_performance()` - 评估信号表现

**风险过滤**：
- 单标的持仓限制检查
- Greeks 水位检查
- 最大回撤保护
- 日内交易次数限制

### 3.2 OrderExecutor - 订单执行引擎

**职责**：自动执行已验证的交易信号，支持批量处理和状态监控。

**执行模式**：
- **DRY_RUN**：模拟执行（测试模式）
- **REAL**：真实下单（Tiger API）

**关键方法**：
- `execute_signal_batch()` - 批量执行
- `_execute_single_signal()` - 单个信号执行
- `_calculate_order_params()` - 计算订单参数
- `monitor_order_status()` - 监控订单状态
- `cancel_signal()` - 取消信号

### 3.3 PerformanceAnalyzer - 性能分析器

**职责**：每日性能评估，识别成功/失败模式，生成改进建议。

**关键方法**：
- `evaluate_daily_performance()` - 每日评估
- `generate_strategy_report()` - 策略报告
- `identify_improvement_opportunities()` - 识别改进
- `_find_extreme_signals()` - 极端表现分析

**评估维度**：
- 胜率 / 盈亏比
- 平均持仓时长
- 最大回撤
- Sharpe Ratio
- 策略效果对比

### 3.4 AdaptiveOptimizer - 自适应优化器

**职责**：基于历史表现自动优化参数。

**优化目标**：
- 信号阈值调整
- 策略权重分配
- 风险参数校准
- 仓位大小优化（Kelly Criterion）

### 3.5 QuantTradingLoop - 闭环协调器

**职责**：整合所有组件，编排完整闭环流程。

**流程**：
```python
async def run_complete_cycle():
    # 1. 策略运行 → 生成信号
    signals = await signal_engine.generate_signals_from_strategy_run(run_id)
    
    # 2. 信号验证 → 风险过滤
    validated = await signal_engine.validate_signals(signals)
    
    # 3. 订单执行
    results = await order_executor.execute_signal_batch(validated)
    
    # 4. 性能监控
    await monitor_positions()
    
    # 5. 每日评估
    performance = await analyzer.evaluate_daily_performance()
    
    # 6. 识别改进
    opportunities = await analyzer.identify_improvement_opportunities()
    
    # 7. 自适应优化
    await optimizer.run_daily_optimization(performance)
```

---

## 4. 服务层设计

### 4.1 Strategy Service

**核心功能**：策略库管理 + 策略运行 + 性能统计

**关键方法**：
```python
class StrategyService:
    async def get_all_strategies(category: Optional[str] = None) -> List[Strategy]:
        """获取策略列表（支持分类筛选）"""
    
    async def get_strategy_detail(strategy_id: int) -> Strategy:
        """获取策略详情（包含参数配置）"""
    
    async def run_strategy(strategy_id: int, account_id: str) -> StrategyRun:
        """运行策略，生成交易信号"""
    
    async def update_strategy_params(strategy_id: int, params: dict):
        """更新策略参数"""
    
    async def toggle_strategy(strategy_id: int) -> bool:
        """启用/禁用策略"""
    
    async def get_strategy_performance(strategy_id: int) -> Dict:
        """获取策略历史表现（胜率/Sharpe/盈亏比）"""
    
    async def get_strategy_signals(strategy_id: int, limit: int = 10) -> List[TradingSignal]:
        """获取策略最近信号"""
```

**策略实现模块**：
- `app/strategies/mean_reversion/` - 均值回归策略实现
- `app/strategies/trend_following/` - 趋势跟踪策略实现
- `app/strategies/multi_factor/` - 多因子策略实现
- `app/strategies/defensive/` - 防御策略实现
- `app/strategies/volatility/` - 波动率策略实现
- `app/strategies/macro_hedge/` - 宏观对冲策略实现

**详细实现**：参见 `docs/STRATEGY_LIBRARY_DESIGN.md` 第4-5章

### 4.2 AI Trade Advisor Service

**核心功能**：多维分析 + AI 综合决策

**决策流程**：
```python
async def evaluate_symbols(symbols: List[str]) -> List[Dict]:
    # 并行获取多维数据
    tasks = [_evaluate_single(sym) for sym in symbols]
    results = await asyncio.gather(*tasks)
    
    # 保存评估历史（UPSERT）
    await _save_evaluation_history(results)
    
    return results

async def _evaluate_single(symbol: str):
    # 并行数据获取
    price, technical, fundamental, kline, equity = await asyncio.gather(
        _safe_get_price(symbol),
        _safe_get_technical(symbol),
        _safe_get_fundamental(symbol),
        _safe_get_kline_analysis(symbol),
        _safe_get_equity(account_id)
    )
    
    # AI 综合决策
    decision = await _generate_ai_decision(
        symbol, price, technical, fundamental, kline, equity
    )
    
    return {
        "symbol": symbol,
        "current_price": price,
        "dimensions": {...},
        "decision": decision
    }
```

**AI Prompt 设计**：
- 结构化输出（JSON 格式）
- 6 大决策维度（技术/基本面/K线/R:R/情景/风险）
- 严格决策原则（R:R < 1:2 → HOLD）

### 4.2 Dashboard V2 Service

**核心功能**：聚合全平台数据，构建实时仪表盘

**数据源**：
- 账户权益（AccountService）
- 持仓信息（PositionMacroService）
- Greeks 敞口（OptionExposureService）
- 信号/计划/告警统计
- AI 洞察

**并行聚合**：
```python
async def get_full_dashboard():
    # 15+ 异步任务并行执行
    tasks = [
        _get_account_overview(),
        _get_pnl_metrics(),
        _get_risk_metrics(),
        _get_signal_summary(),
        _get_plan_summary(),
        # ...
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 错误隔离：单个模块失败不影响整体
    return DashboardV2Response(...)
```

**性能优化**：
- Redis 缓存（60s TTL）
- 快速接口（/quick）：仅返回核心KPI

### 4.3 Technical Analysis Service

**功能**：计算技术指标并缓存

**指标覆盖**：
- 趋势：SMA/EMA/布林带
- 动量：RSI/MACD/Stochastic
- 成交量：Volume Ratio
- 支撑阻力位识别
- AI 摘要生成

**缓存策略**：
- Redis 缓存 1 小时
- force_refresh 参数强制刷新

### 4.4 Behavior Scoring Service

**功能**：识别交易坏习惯，给出行为评分

**评分维度**：
- **Sell Fly Score**：卖出后继续上涨
- **Discipline Score**：止损执行纪律
- **Overall Behavior Score**：综合健康度

**计算逻辑**：
```python
sell_fly_score = 100 - (sell_fly_count / total_sells * 100)
discipline_score = on_time_stop_loss_count / total_stop_loss * 100
behavior_score = (discipline_score * 0.6 + sell_fly_score * 0.4)
```

---

### 4.5 V10 新增服务设计

#### RiskGateService — 非绕过风险门

```python
class RiskGateService:
    """在任何自主决策下单前必须通过此门，无法绕过"""
    
    async def check(self, account_id: str, symbol: str, qty: float, side: str) -> RiskGateResult:
        """
        1. 计算执行后持仓权重 → 超过 MAX_SINGLE_POSITION_PCT 则拒绝
        2. 运行 VaR@95% 估算 → 超过 MAX_VAR_PCT 则拒绝
        3. 运行内置压力情景（GFC/COVID/2022）→ 超过 MAX_STRESS_LOSS_PCT 则拒绝
        4. 检查当日已执行笔数 → 超过 MAX_DAILY_TRADES 则拒绝
        5. 检查当日已实现亏损 → 超过 MAX_DAILY_LOSS_PCT 则触发熔断
        """

class RiskGateResult(BaseModel):
    passed: bool
    reason: Optional[str]          # 拒绝原因
    circuit_breaker: bool = False   # 是否触发熔断
    details: dict                   # VaR值、压测结果等
```

#### AutonomousEngine — AI 自主决策引擎

```python
class AutonomousEngine:
    """三级自主模式：FULL / SEMI（默认）/ ADVISORY"""
    
    async def run_decision_cycle(self, account_id: str):
        # 1. 拉取信号（来自已运行的 StrategyRun）
        signals = await strategy_service.get_pending_signals(account_id)
        
        # 2. 调用 AI 复杂推理模型做决策
        decision = await self._ai_decide(signals)
        # decision = {"action":"BUY","symbol":"AAPL","qty":50,
        #             "algo":"TWAP","confidence":0.82,"reasoning":"..."}
        
        # 3. RiskGate 不可绕过检查
        gate = await risk_gate.check(account_id, decision.symbol, decision.qty, decision.action)
        if not gate.passed:
            await self._log_rejection(account_id, decision, gate)
            return
        
        # 4. 按自主级别执行
        level = settings.AI_AUTONOMY_LEVEL
        if level == "FULL":
            await self._auto_execute(account_id, decision)
        elif level == "SEMI":
            order_id = await self._auto_execute(account_id, decision)
            # 30 分钟内可撤单
            await self._schedule_revoke_window(account_id, order_id, minutes=30)
        else:  # ADVISORY
            await self._notify_suggestion(account_id, decision)
        
        # 5. 写 autonomy_audit_log
        await self._audit(account_id, decision, gate, order_id)
```

#### BacktestRunner — 事件驱动回测 + Walk-Forward

```python
class BacktestRunner:
    async def run(self, task: BacktestTask) -> dict:
        """
        事件驱动回测：
        1. 拉取历史 OHLCV（DataHub）
        2. 按 bar 驱动策略 signal 函数
        3. 模拟撮合（滑点 0.05%，交易费 0.1%）
        4. 若 walk_forward=True，滚动窗口 in-sample/out-of-sample 验证
        5. 计算绩效指标：Sharpe / Sortino / MaxDrawdown / WinRate / Alpha
        """

    def _check_graduation(self, result: dict) -> bool:
        """Paper→Live 毕业检查：Sharpe≥1.0 且 MaxDrawdown≤20% 且 WinRate≥50%"""
        return (result["sharpe"] >= 1.0 and 
                abs(result["max_drawdown"]) <= 0.20 and 
                result["win_rate"] >= 0.50)
```

#### PortfolioOptimizer — 有效前沿优化

```python
class PortfolioOptimizer:
    async def optimize(self, account_id: str, method: str = "MARKOWITZ") -> dict:
        """
        MARKOWITZ: scipy.optimize 最大化 Sharpe，输出权重+有效前沿散点
        RISK_PARITY: 各资产等风险贡献
        KELLY: Kelly fraction（半Kelly，max 25%）
        返回：{target_weights, current_weights, frontier_points, expected_return, expected_vol}
        """
```

#### TwapVwapService — 执行算法

```python
class TwapVwapService:
    async def submit(self, task: AlgoTask) -> str:
        """注册算法执行任务，返回 task_id"""
    
    async def run_twap_slice(self, task_id: str):
        """TWAP：将总量均分为 N 片，每隔 interval_secs 执行一片"""
    
    async def run_vwap_slice(self, task_id: str, market_volume: float):
        """VWAP：按实时成交量比例分配每片数量"""
```

#### CopilotService — 对话式 AI 助理

```python
class CopilotService:
    async def chat(self, account_id: str, session_id: str, message: str) -> CopilotResponse:
        """
        1. 轻量查询 → deepseek-chat/gpt-4o-mini（历史、状态查询）
        2. 复杂分析/操作意图 → deepseek-reasoner/gpt-5.2
        3. 若检测到操作意图：返回 action_intent + 需要人工确认
        """
    
    async def morning_brief(self, account_id: str) -> str:
        """每日 08:15 生成盘前摘要（AI 复杂模型）"""
    
    async def confirm_action(self, account_id: str, action_id: str) -> bool:
        """执行 Copilot 建议的操作（须人工确认）"""
```

---

## 5. 定时任务设计

使用 APScheduler 实现周期性任务：

```python
# 每小时刷新技术指标
scheduler.add_job(
    refresh_technical_indicators_job,
    trigger="interval",
    hours=1,
    id="refresh_technical_indicators"
)

# 每日凌晨生成权益快照
scheduler.add_job(
    generate_equity_snapshot_job,
    trigger="cron",
    hour=0,
    minute=5,
    id="daily_equity_snapshot"
)

# 每日评估性能
scheduler.add_job(
    evaluate_daily_performance_job,
    trigger="cron",
    hour=0,
    minute=30,
    id="daily_performance_evaluation"
)
```

---

## 6. API Rate Limit 监控

**目的**：避免外部 API 超限

**监控对象**：
- FRED (宏观数据)
- NewsAPI (新闻)
- Tiger (行情)
- OpenAI (AI)

**实现**：
- Redis 计数器（滑动窗口）
- 智能告警（70% 警告，90% 临界）
- 自动降级策略

**端点**：
- GET `/api/v1/stats/{provider}` - 查询统计
- GET `/api/v1/rate-limit/{provider}` - 检查限额
- GET `/api/v1/report` - 完整监控报告

---

## 7. 安全设计

### 7.1 认证与授权

- **JWT Token**：HS256 签名，7 天有效期
- **密码加密**：bcrypt 哈希（cost=12）
- **API Key 管理**：环境变量 + 加密存储

### 7.2 操作审计

所有敏感操作记录到 `audit_logs` 表：
- 订单创建/取消
- 计划执行
- 风控参数调整
- 策略运行

### 7.3 访问控制

- Rate Limit：100 req/min per IP
- 策略管理：仅授权用户（STRATEGY_MANAGE_USERS）
- 订单执行：需二次确认（高风险）

---

## 8. 性能优化

### 8.1 数据库优化

- 异步 SQLAlchemy（AsyncSession）
- 索引优化（account_id + created_at）
- 分页查询（避免全表扫描）
- 连接池（pool_size=10）

### 8.2 缓存策略

- Redis 缓存关键数据：
  - 技术指标：1 小时
  - 基本面数据：24 小时
  - 宏观数据：24 小时
  - Dashboard 聚合：60 秒

### 8.3 并行处理

- `asyncio.gather()` 并行 I/O
- 多标的评估并发执行
- 错误隔离（return_exceptions=True）

---

## 9. 部署架构

```
┌─────────────┐
│   Nginx     │ (反向代理 + SSL)
└──────┬──────┘
       │
┌──────▼──────────────┐
│  FastAPI (Uvicorn)  │ × 4 workers
└──────┬──────────────┘
       │
   ┌───┴───┬────────┬────────┐
   │       │        │        │
┌──▼──┐ ┌──▼──┐  ┌──▼──┐  ┌──▼──┐
│MySQL│ │Redis│  │Tiger│  │OpenAI│
└─────┘ └─────┘  └─────┘  └──────┘
```

**环境变量**：
- `.env` - 本地开发
- `.env.production` - 生产环境
- Docker Compose 部署

---

## 10. 测试策略

### 10.1 单元测试

- 核心引擎逻辑测试
- 服务层业务逻辑测试
- Mock 外部依赖（Tiger/OpenAI）

### 10.2 集成测试

- API 端点测试
- 数据库事务测试
- 定时任务测试

### 10.3 E2E 测试

- 完整交易闭环测试
- Dashboard 数据聚合测试
- WebSocket 推送测试

---

## 11. 监控与告警

### 11.1 日志系统

- **Loguru** 结构化日志
- 日志级别：DEBUG/INFO/WARNING/ERROR
- 日志滚动：100MB/天

### 11.2 健康检查

- GET `/health` - 服务状态
- GET `/api/v1/monitoring/health` - 详细健康检查

### 11.3 告警机制

- API 超限告警
- 订单执行失败告警
- 系统异常告警
- Telegram 推送

---

## 附录

### A. 数据库迁移

使用 Alembic 管理数据库版本：

```bash
# 生成迁移脚本
alembic revision --autogenerate -m "add equity snapshots"

# 执行迁移
alembic upgrade head

# 回滚
alembic downgrade -1
```

### B. 环境变量示例

```env
# 数据库
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATABASE_NAME=ai_trading
DATABASE_USER=root
DATABASE_PASSWORD=***

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Tiger
TIGER_ACCOUNT=***
TIGER_API_KEY=***
TIGER_SECRET=***

# OpenAI
OPENAI_API_KEY=***
DEEPSEEK_API_KEY=***

# JWT
JWT_SECRET=***
JWT_ALGORITHM=HS256
JWT_EXPIRE_DAYS=7
```

### C. 参考文档

- API.md - API 接口文档
- PRODUCT.md - 产品需求文档
- FRONTEND_DESIGN.md - 前端设计文档
- STRATEGY_LIBRARY_DESIGN.md - 策略库扩充设计文档（新增）
