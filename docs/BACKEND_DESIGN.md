# 后端架构设计文档

> **AI量化交易闭环系统** - Backend Design  
> 版本：V9.0 | 更新日期：2026-02-13

---

## 1. 架构概览

### 1.1 技术栈

- **框架**：FastAPI 0.109+ (ASGI)
- **数据库**：MySQL 8.0 + SQLAlchemy 2.0 (Async)
- **缓存**：Redis 7.0
- **调度器**：APScheduler
- **券商接口**：Tiger Trade API
- **AI**：OpenAI GPT-4 + DeepSeek

### 1.2 项目结构

```
# 仓库（扁平化后）
├── app/
│   ├── main.py                    # FastAPI 应用入口
│   ├── core/
│   │   ├── config.py             # 环境配置（Pydantic Settings）
│   │   ├── security.py           # JWT + bcrypt
│   │   └── dependencies.py       # 依赖注入
│   │  
│   ├── models/                   # SQLAlchemy 数据模型 (15+ 表)
│   │   ├── db.py                 # 异步引擎 + SessionLocal
│   │   ├── trading_signal.py     # 交易信号
│   │   ├── trading_plan.py       # 交易计划
│   │   ├── equity_snapshot.py    # 账户权益快照
│   │   ├── trade_journal.py      # 交易日志
│   │   ├── price_alert.py        # 价格告警
│   │   ├── ai_evaluation_history.py  # AI 评估历史
│   │   └── ...                   # 策略/持仓/行为评分等
│   │
│   ├── schemas/                  # Pydantic 响应模型
│   │   ├── dashboard_v2.py       # Dashboard V2 数据结构
│   │   ├── signals.py
│   │   ├── trading_plan.py
│   │   └── ...
│   │
│   ├── services/                 # 业务逻辑层 (20+ 服务)
│   │   ├── ai_trade_advisor_service.py  # AI 交易决策
│   │   ├── signal_service.py     # 信号管理
│   │   ├── trading_plan_service.py      # 计划管理
│   │   ├── order_service.py      # 订单执行
│   │   ├── dashboard_v2_service.py      # Dashboard V2
│   │   ├── technical_analysis_service.py
│   │   ├── fundamental_analysis_service.py
│   │   ├── behavior_scoring_service.py
│   │   ├── alert_service.py
│   │   ├── equity_service.py
│   │   ├── journal_service.py
│   │   └── ...
│   │
│   ├── engine/                   # 核心引擎
│   │   ├── signal_engine.py      # 信号引擎
│   │   ├── order_executor.py     # 订单执行引擎
│   │   ├── performance_analyzer.py # 性能分析器
│   │   ├── adaptive_optimizer.py # 自适应优化器
│   │   ├── quant_trading_loop.py # 闭环协调器
│   │   ├── auto_hedge_engine.py  # 自动对冲引擎（已有）
│   │   └── alert_engine.py       # 价格告警引擎
│   │
│   ├── routers/                  # API 路由层 (16+ 端点组)
│   │   ├── dashboard_v2.py       # GET /api/v1/dashboard/v2/{full,quick}
│   │   ├── ai_advisor.py         # AI 决策相关
│   │   ├── signals.py            # 信号管理
│   │   ├── trading_plan.py       # 计划管理
│   │   ├── strategies.py         # 策略库管理（新增）
│   │   ├── positions.py          # 持仓评估
│   │   ├── macro_risk.py         # 宏观风险
│   │   ├── opportunities.py      # 潜在机会
│   │   ├── alerts.py             # 价格告警
│   │   ├── equity.py             # 资金曲线
│   │   ├── journal.py            # 交易日志
│   │   ├── orders.py             # 订单管理
│   │   ├── websocket.py          # WebSocket 推送
│   │   └── ...
│   │
│   ├── broker/                   # 券商接口封装
│   │   ├── tiger_option_client.py
│   │   └── mock_client.py        # 测试用
│   │
│   ├── jobs/                     # 定时任务
│   │   ├── data_refresh_jobs.py  # 技术指标刷新
│   │   ├── signal_jobs.py        # 信号扫描
│   │   ├── performance_jobs.py   # 性能评估
│   │   └── equity_snapshot_job.py # 每日权益快照
│   │
│   └── utils/                    # 工具类
│       ├── cache.py              # Redis 缓存装饰器
│       ├── logger.py             # Loguru 日志
│       └── ...
│
├── tests/                        # 单元测试 + 集成测试
├── requirements.txt
└── .env                          # 环境变量
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
