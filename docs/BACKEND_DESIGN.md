# 后端架构设计文档

> **AI量化交易闭环系统** - Backend Design  
> 版本：V10.5.4（规划中） | 更新日期：2026-03-11
>
> **V10.5.4 变更摘要（Signal Pipeline Integrity & Control-Plane Hardening）**：本版本先收敛信号控制平面，再继续推进 Profit Engine。后端围绕四条主线推进：**Signal Discovery Integrity**（`signal_origin_mode=REAL/SYNTHETIC/BACKFILL` 真源区分）、**Canonical Signal Payload & State Machine**（统一 payload、原生状态迁移、恢复语义）、**Autonomous Control Plane Hardening**（明确 `AutonomousEngine.run_decision_cycle()` 为唯一自动执行主链，统一 positions / regime / audit 真源，补齐 displacement pending 闭环）、**Native Audit & Governance Discipline**（Watchtower 原生审计优先、完整开发流程、`Observe → Shadow → Semi → Full` 分阶段 rollout）。
>
> **V10.5.2 变更摘要（组合席位竞争引擎）**：**Capacity-Aware Admission & Replacement Engine**——SignalQualityFunnel Layer 2 从满仓即拒绝升级为统一席位竞争：新增 CapacityArbiterService（统一候选池 + admission_score 排序 + overflow 淘汰算法）；AutonomousEngine 在 RiskGate 前引入 unified capacity decision；PositionRebalanceMonitor 升级为席位竞争数据供应方与兜底守卫；PositionScoringService 补齐统一准入评分接口；新增 capacity_decision_audit_log 数据表，记录候选评分、淘汰原因、保护带结果；支持治理开关 CAPACITY_REPLACEMENT_ENABLED / DRY_RUN / MAX_PER_CYCLE / MIN_EDGE；新增 /api/v1/capacity-arbiter/ 路由组（preview、audit-log、config）；V10.5.1 补丁随本版合并发布：post_mortem_jobs.py EventBus + Cron 自动化 + 事件日历 freshness 修复 + confirmed=False 体制修复。
>
> **V10.4.3 变更摘要（风险降低优先执行）**：**减仓/平仓快速通道**——`RiskGateService.check(..., signal_intent=...)` 识别 `REDUCE/EXIT/STOP_LOSS_EXIT/FORCE_EXIT`，对风险降低类订单豁免日交易笔数 / VaR / 压力测试检查，并支持 `ALLOW_CLOSING_DURING_CIRCUIT_BREAKER=true` 在熔断期间放行平仓；`AutonomousEngine` 新增 `STANDARD / FAST_CLOSE / FORCE_EXIT` 三种执行路径，关闭类信号默认跳过 `SignalQualityFunnel`，`force_exit=true` 时进一步跳过冷却与 Redis 锁；`SignalPositionFilter` 会把超持仓的 `REDUCE` 自动升级为 `EXIT`；`OrderExecutor` 对 `EXIT/REDUCE` 使用实际持仓数量并允许港股 odd-lot 退出；`/api/v1/autonomy/status|audit-log|signal-pipeline` 暴露 `execution_path / bypass_reason / force_exit` 观测字段。**补充**：开仓型信号在进入漏斗前先由 `SignalQualityFunnel.preview_quality()` 计算 `LOW / MEDIUM / HIGH / ELITE` 质量标签并排序入队，`ELITE` 信号仅豁免 Layer 2 的 `MAX_DAILY_SIGNALS` 检查，不豁免仓位/相关性/RiskGate。  
> **V10.4.2 变更摘要（信号精英化）**：**五层信号漏斗**——`SignalQualityConfig`（Pydantic BaseSettings，支持热加载）+ `SignalConvictionScorer`（Conviction Score：composite×0.4 + resonance_bonus×0.25 + regime_alignment×0.15 + historical_ic×0.1 + timing_quality×0.1）+ `SignalQualityFunnel`（Layer 0 宇宙过滤 / Layer 1 体制门控 / Layer 2 组合预检 / Layer 3 多维共振 / Layer 4 置信度校准门）+ `anti_resonance_kill_switch`（tech/fundamental 对立 或 CRISIS 做多 → conviction 强制归零）+ **幽灵交易**——`GhostTradeService`（Layer 3/4 拒绝信号自动虚拟跟踪，每日价格更新，计算幽灵胜率 vs 实际胜率对比）+ **审计日志**——`SignalQualityAuditLog`（每个信号的漏斗结果全量记录）+ `AutonomousEngine` 决策前接入漏斗（硬约束 `MAX_CONCURRENT_POSITIONS=6` / `MAX_DAILY_SIGNALS=5`）+ 6 个新增 API 端点（`/api/v1/signals/quality-config`·`/audit-log`·`/funnel-stats`·`/ghost-trades`·`/ghost-trades/analysis`）+ `ghost_trade_jobs.py`（每日收盘后更新幽灵 PnL）+ 2 张新增 DB 表（`signal_quality_audit_logs` / `ghost_trades`）
>
> **V10.4.1 变更摘要**：**M1 数据闭环治理**——`ReturnBackfillJob`（每日 21:30 ET，自动回填 `TradingSignal.actual_return`，回填率 ≥95%，触发 IC 增量重算）+ IC `data_quality` 字段全覆盖（`REAL`/`INSUFFICIENT`/`STALE`，移除 expected_return 代理收益）+ 因子敞口零快照（无持仓时写入 positions_count=0 快照，不跳过）+ `LLMCallGuard`（超时30s+指数退避重试+降级返回 degraded=true）+ `LlmCallLog` 表（model/latency/tokens/status 全量记录）；**M3 Copilot 上下文服务**——`GET /api/v1/copilot/context` 返回当前系统快照供浮层注入；**M4 自主循环稳定**——`AutonomyHealthMonitorService`（10分钟8项自检）+ `JobWatchdog`（Job 超时2x触发补跑）+ `register_m4_jobs()` 导入 main.py。
>
> **V10.3.4 变更摘要**：稳定性与冷启动治理——全服务冷启动占位逻辑 + `market_universe` 表 + PostMortem 交易选择驱动 + REDUCE/EXIT 信号规则执行 + 事件去重索引 + 多账户 ID 兼容。
>
> **V10.3.3 变更摘要**：**可观测性 2.0**——`ExecutionMicroscopeService`（IS 四分解：delay/impact/opportunity/timing cost，写入 `execution_quality_log`）+ `SignalIntelligenceService`（六维 IC 滚动序列 + Alpha 半衰期 + 拥挤度检测）+ `RiskObservabilityService`（五因子敞口 5 分钟快照写入 `portfolio_factor_exposure` + ES@97.5% + 相关性骤升告警）；**AI 中枢 2.0**——`MultiAgentOrchestrator`（五专职 Agent 协作框架，`AgentMessage` 写入 `agent_communication_log`，`RiskChallengerAgent` 强制反驳 BUY）+ `ConfidenceCalibrationService`（置信度 bucket→胜率映射，Brier/ECE，写入 `confidence_calibration_snapshot`，ECE>0.12 触发降评）+ `AdaptiveFactorWeightingService`（Kalman Filter 在线权重更新，写入 `signal_weight_history`）+ `DecisionPostMortemService`（平仓后反事实三路径剖析，写入 `decision_post_mortems`，自动反哺 InsightService）；**War Room**——`WarRoomService`（P&L Ticker 聚合 + Intelligence Feed urgency 排序 + 组合敞口 + SmartAlertService AI分级聚合）；3 个新 API 路由组（`/observability` 11 端点 / `/ai-hub` 9 端点 / `/war-room` 8 端点）；6 张新增 DB 表；每日 08:15 校准 Job + 每日收盘 Kalman 权重更新 Job。
>
> **V10.2-M2~M8 变更摘要**：EventCalendar 事件日历（盈利/FOMC/CPI/NFP）、EarningsFence 盈利围栏（50%仓位上限）、PositionStateMachine 动态仓位生命周期（加仓/减仓/移动止损）、SignalFusionEngine 六维加权融合信号（tech 25%/fundamental 20%/macro 15%/vol 15%/opt 15%/sent 10%）、TradeAttributionEngine 三层归因（Alpha源/执行质量/仓位管理）、InsightService + ABTestEngine AI洞察进化（deepseek-reasoner 周报 + scipy t-test A/B实验）、CopilotPartnerService 深度研究引擎（多步 deep-research）、4张新增 DB 表、17个新增 API 端点、2个新增定时 Job。
>
> **V10.2-M1 变更摘要**：EventBus 异步事件总线（Topics.REGIME_CHANGED/SIGNAL_GENERATED）、MarketRegime 数据模型、RegimeClassifier（五维评分+6类体制+3日确认）、StrategyWeightAllocator（订阅 REGIME_CHANGED 更新 TaskConfig）、RiskGate VaR 体制自适应倍数、审计日志 regime_at_decision 列、/api/v1/regime 4 个端点、每日 08:00 体制分类 Job。
> 
> **V10.1 变更摘要**：Tiger 真实下单接入（美股/港股/期权）、SEMI/FULL 模式 Telegram 通知落地、Copilot 操作指令执行落地、Dashboard 仪表盘数据脱虚向实、AI 组合级决策 + 结构化 JSON 输出、Dashboard 2秒极速性能优化。
> 
> **V10.0 变更摘要**：AI 自主决策引擎（三级自主模式）、DataHub 多源路由、BacktestEngine（Walk-Forward）、PortfolioOptimizer（Markowitz+Kelly）、RiskGate 风险门、压力测试服务、TWAP/VWAP 执行算法、Trading Copilot、Paper Trading、期权分析中心（只读）、AI 周报服务、6 张新增 DB 表。

---

## 1. 架构概览

### 1.1 技术栈

- **框架**：FastAPI 0.109+ (ASGI)
- **数据库**：MySQL 8.0 + SQLAlchemy 2.0 (Async)
- **缓存**：Redis 7.0
- **调度器**：APScheduler
- **通知系统**：Telegram Bot API
- **券商接口**：Tiger Trade API OpenAPI
- **AI**：OpenAI（gpt-4o-mini / gpt-5.2）+ DeepSeek（deepseek-chat / deepseek-reasoner）
- **数据源**：Tiger API（美股/港股/期权实时报价，首选）→ yfinance（美股降级）→ FRED（宏观）— DataHub 多源路由；港股与期权行情与美股使用同一 Tiger API 通道，无需 Futu 独立数据源。

### 1.2 AI 模型路由策略与输出规范

#### 1.2.1 路由策略

| 场景 | 轻量（默认，极速响应） | 复杂推理（深度分析） |
|------|-------------|---------|
| Copilot 对话 | deepseek-chat / gpt-5-mini | deepseek-reasoner / gpt-5.2 |
| 自主决策引擎 | — | deepseek-reasoner / gpt-5.2 |
| 周报/深度分析 | — | deepseek-reasoner / gpt-5.2 |
| 信号简单摘要 | deepseek-chat / gpt-5-mini | — |

路由逻辑：`AI_LIGHTWEIGHT_MODEL` / `AI_COMPLEX_MODEL` 从 config 读取；客户端统一使用 `BaseAIClient`。

#### 1.2.2 结构化输出规范 (V10.1)

为了解决正则解析不稳定的问题，V10.1 全面切换至结构化输出（JSON Output Mode）：
- 意图检测、风控决策、执行指令统一使用 `response_format={"type": "json_object"}`。
- 禁止在系统提示词之外通过 Regex 提取字段。
- AI 响应必须符合预定义的 Pydantic Schema。

#### 1.2.3 V10.5.4 rollout 运行纪律

- `SIGNAL_PIPELINE_V1054_ENABLED=false`：**OBSERVE**，只校验 `signal_origin_mode` / canonical `signal_payload` / native `signal_transitions` 的覆盖率与一致性。
- `SIGNAL_PIPELINE_V1054_ENABLED=true`：**SHADOW**，开始在控制台与研究页展示真源 / payload / transition 差异，但不接管 live 决策。
- `AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED=true` 且 `NATIVE_AUDIT_V1054_ENABLED=true`：**SEMI**，原生控制面与审计路径开始灰度接管。
- 再叠加 `GOVERNANCE_HARD_GATE_ENABLED=true`：**FULL**，进入原生治理闭环。
- 运维顺序建议固定为：**迁移 → 回补 → 修复 → 验收 → 灰度开关**。避免先开开关、后补历史，导致页面口径与真实控制面错位。

### 1.3 项目结构

```
├── app/
│   ├── main.py                        # FastAPI 应用入口（V10.2: 注册 25 个路由组）
│   ├── core/
│   │   ├── config.py                  # V10.2-M1: 新增 4 个 REGIME_* 配置项
│   │   ├── event_bus.py               # V10.2-M1 新增：AsyncIO 异步事件总线
│   │   ├── security.py                # JWT + bcrypt
│   │   └── dependencies.py            # 依赖注入
│   │
│   ├── data/
│   │   └── hub.py                     # V10 新增：DataHub 多源路由
│   │
│   ├── models/                        # SQLAlchemy 数据模型 (26+ 表)
│   │   ├── ...（原有 15 张表）
│   │   ├── backtest_task.py           # V10 新增
│   │   ├── portfolio_snapshot.py      # V10 新增
│   │   ├── paper_account.py           # V10 新增
│   │   ├── copilot_message.py         # V10 新增
│   │   ├── algo_execution_task.py     # V10 新增
│   │   ├── autonomy_audit_log.py      # V10 新增; V10.2-M1 新增 regime_at_decision 列
│   │   ├── market_regime.py           # V10.2-M1 新增：市场体制历史表
│   │   ├── event_calendar.py          # V10.2-M2 新增：事件日历表（盈利/FOMC/CPI 等）
│   │   ├── trade_attribution.py       # V10.2-M5 新增：交易三层归因记录表
│   │   └── ai_insight.py              # V10.2-M6 新增：AI洞察知识库 + A/B实验表
│   │
│   ├── schemas/                       # Pydantic 响应模型
│   │   └── ...（原有 + 14 组新增，含 regime/events/positions_lifecycle/signals/attribution/insights）
│   │
│   ├── services/                      # 业务逻辑层 (40+ 服务)
│   │   ├── ...（原有 20 个服务）
│   │   ├── risk_gate_service.py       # V10 新增; V10.2-M1 新增 set_regime_var_multiplier()
│   │   ├── autonomous_engine.py       # V10 新增; V10.2-M1 审计日志注入 regime_at_decision
│   │   ├── regime_classifier.py       # V10.2-M1 新增：五维评分体制分类器
│   │   ├── regime_strategy_allocator.py # V10.2-M1 新增：体制感知策略权重分配器
│   │   ├── stress_test_service.py     # V10 新增
│   │   ├── twap_vwap_service.py       # V10 新增：执行算法
│   │   ├── copilot_service.py         # V10 新增：对话式接口
│   │   ├── options_analysis_service.py # V10 新增（只读）
│   │   ├── paper_trading_service.py   # V10 新增
│   │   ├── weekly_report_service.py   # V10 新增
│   │   ├── event_calendar_service.py  # V10.2-M2 新增：yfinance 盈利 + 硬编码 FOMC/CPI/NFP 日历
│   │   ├── earnings_fence_service.py  # V10.2-M2 新增：50% 仓位上限围栏逻辑
│   │   ├── dynamic_position_service.py # V10.2-M3 新增：PositionStateMachine + ScaleIn/Out + TrailingStop
│   │   ├── signal_fusion_engine.py    # V10.2-M4 新增：六维加权融合（含体制倍数）
│   │   ├── trade_attribution_engine.py # V10.2-M5 新增：三层归因（Alpha源/执行/仓位管理）
│   │   ├── insight_service.py         # V10.2-M6 新增：InsightService + WeeklyInsightGenerator + ABTestEngine
│   │   └── copilot_partner_service.py # V10.2-M7 新增：ProactiveIntelligence + DeepResearchEngine
│   │
│   ├── engine/                        # 核心引擎
│   │   ├── signal_engine.py
│   │   ├── order_executor.py
│   │   ├── performance_analyzer.py
│   │   ├── adaptive_optimizer.py
│   │   ├── quant_trading_loop.py
│   │   ├── auto_hedge_engine.py
│   │   ├── alert_engine.py
│   │   ├── backtest/                  # V10 新增
│   │   │   ├── __init__.py
│   │   │   └── runner.py              # 事件驱动回测 + Walk-Forward
│   │   └── portfolio/                 # V10 新增
│   │       └── optimizer.py           # Markowitz + Kelly
│   │
│   ├── routers/                       # API 路由层 (30 个端点组)
│   │   ├── ...（原有 16 个路由）
│   │   ├── autonomy.py                # V10 新增
│   │   ├── copilot.py                 # V10 新增; V10.2-M7 新增 POST /deep-research
│   │   ├── backtest.py                # V10 新增
│   │   ├── portfolio.py               # V10 新增
│   │   ├── stress_test.py             # V10 新增
│   │   ├── paper_trading.py           # V10 新增
│   │   ├── options_analysis.py        # V10 新增
│   │   ├── execution_algo.py          # V10 新增
│   │   ├── regime.py                  # V10.2-M1 新增：/api/v1/regime 4 个端点
│   │   ├── events.py                  # V10.2-M2 新增：/api/v1/events 5 个端点
│   │   ├── position_lifecycle.py      # V10.2-M3 新增：/api/v1/positions 生命周期 3 个端点
│   │   ├── signal_fusion.py           # V10.2-M4 新增：/api/v1/signals 2 个端点
│   │   ├── attribution.py             # V10.2-M5 新增：/api/v1/attribution 2 个端点
│   │   └── insights.py                # V10.2-M6 新增：/api/v1/insights 5 个端点
│   │
│   ├── broker/
│   ├── jobs/
│   │   ├── ...（原有 6 个 Job 文件）
│   │   ├── regime_jobs.py             # V10.2-M1 新增：每日 08:00 体制分类 Job
│   │   ├── event_jobs.py              # V10.2-M2 新增：每日 07:00 事件日历同步 Job
│   │   └── insight_jobs.py            # V10.2-M6 新增：周日 22:00 ET 洞察生成 + 每日 08:00 A/B检验 Job
│   └── utils/
│
├── scripts/
│   └── migrations/
│       ├── v10_2_m1_market_regimes.py  # V10.2-M1 DB 迁移脚本
│       └── upgrade_to_v10_2_m2_m8.py  # V10.2-M2~M8 DB 迁移脚本（4张新表）
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
CREATE TABLE copilot_messages (  -- role VARCHAR(16) fixed from VARCHAR(8)
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

### 2.3 V10.2 新增表

#### M. event_calendar_entries — 事件日历

```sql
CREATE TABLE event_calendar_entries (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  symbol VARCHAR(32) COMMENT '标的（FOMC/CPI/NFP 类事件为空）',
  event_type VARCHAR(32) NOT NULL COMMENT 'EARNINGS/FOMC/CPI/NFP/OTHER',
  event_date DATE NOT NULL,
  risk_level VARCHAR(16) NOT NULL DEFAULT 'MEDIUM' COMMENT 'LOW/MEDIUM/HIGH/CRITICAL',
  fence_active BOOLEAN DEFAULT FALSE COMMENT '围栏是否激活',
  fence_overridden BOOLEAN DEFAULT FALSE COMMENT '是否被人工覆盖',
  override_reason TEXT,
  eps_estimate DECIMAL(10,4),
  eps_actual DECIMAL(10,4),
  revenue_estimate DECIMAL(20,2),
  revenue_actual DECIMAL(20,2),
  reaction_pct DECIMAL(10,4) COMMENT '盈利公布后24h价格反应%',
  source VARCHAR(32) DEFAULT 'yfinance' COMMENT '数据来源',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_symbol_date (symbol, event_date),
  INDEX idx_event_date (event_date),
  INDEX idx_risk (risk_level)
);
```

**用途**：存储盈利/FOMC/CPI/NFP 等高影响力事件，用于盈利围栏逻辑判断。

#### N. trade_attribution_entries — 交易归因记录

```sql
CREATE TABLE trade_attribution_entries (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  trade_id VARCHAR(64) NOT NULL COMMENT '关联 autonomy_audit_log 或 trade_journal',
  symbol VARCHAR(32) NOT NULL,
  direction VARCHAR(8) NOT NULL,
  entry_price DECIMAL(20,6),
  exit_price DECIMAL(20,6),
  quantity DECIMAL(20,6),
  realized_pnl DECIMAL(20,2),
  -- Layer 1: Alpha 源归因
  alpha_pnl DECIMAL(20,2) COMMENT 'Alpha来源贡献PnL',
  alpha_source VARCHAR(64) COMMENT '信号来源策略/维度',
  alpha_confidence DECIMAL(5,2),
  -- Layer 2: 执行质量归因
  exec_pnl DECIMAL(20,2) COMMENT '执行质量贡献PnL（滑点/时机）',
  exec_quality_score DECIMAL(5,2) COMMENT '0-100',
  exec_algo VARCHAR(16) COMMENT 'MKT/TWAP/VWAP',
  slippage_bps DECIMAL(10,4),
  -- Layer 3: 仓位管理归因
  pos_mgmt_pnl DECIMAL(20,2) COMMENT '仓位管理贡献PnL',
  stop_adjustment_count INT DEFAULT 0,
  scale_in_count INT DEFAULT 0,
  scale_out_count INT DEFAULT 0,
  market_regime_at_entry VARCHAR(32),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_time (account_id, created_at),
  INDEX idx_symbol (symbol),
  INDEX idx_alpha_source (alpha_source)
);
```

**用途**：记录每笔已平仓交易的三层归因，驱动 AttributionPage 可视化分析。

#### O. ai_insight_repository — AI 洞察知识库

```sql
CREATE TABLE ai_insight_repository (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  insight_type VARCHAR(32) NOT NULL COMMENT 'WEEKLY_SUMMARY/PATTERN/LESSON/RULE_CANDIDATE',
  title VARCHAR(256) NOT NULL,
  body TEXT NOT NULL,
  confidence DECIMAL(5,2) DEFAULT 0.5 COMMENT '0-1，AI生成时写入，可人工调整',
  active BOOLEAN DEFAULT TRUE COMMENT '是否激活（停用后不影响新决策）',
  source_trades JSON COMMENT '关联的 trade_id 列表',
  model_used VARCHAR(64),
  generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_type_active (insight_type, active),
  INDEX idx_generated (generated_at)
);
```

#### P. ab_experiments — A/B 实验

```sql
CREATE TABLE ab_experiments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL UNIQUE,
  description TEXT,
  hypothesis TEXT,
  control_params JSON NOT NULL COMMENT '对照组参数',
  test_params JSON NOT NULL COMMENT '实验组参数',
  target_metric VARCHAR(64) NOT NULL COMMENT '评估指标名称（如 sharpe/win_rate）',
  status VARCHAR(16) DEFAULT 'RUNNING' COMMENT 'RUNNING/COMPLETED/PAUSED',
  start_date DATE NOT NULL,
  end_date DATE,
  control_result JSON COMMENT '对照组统计结果',
  test_result JSON COMMENT '实验组统计结果',
  p_value DECIMAL(10,6) COMMENT 'scipy t-test p 值',
  statistical_significance BOOLEAN COMMENT 'p < 0.05',
  conclusion TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_status (status)
);
```

**用途**：A/B 实验管理，自动运行 scipy t-test 确认结果显著性（p<0.05）。

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

### 3.2 OrderExecutor - 订单执行与实盘接入

**职责**：自动执行已验证的交易信号，支持批量处理和状态监控。

**执行模式与接入 (V10.1)**：
- **PAPER_TRADING**：模拟执行，读写 `paper_accounts`。
- **LIVE_TRADING**：实盘接入，通过 `TigerOrderExecutor` 对转 Tiger OpenAPI。
- **支持标的**：美股、港股、美股期权、港股期权（统一走 Tiger 通道）。

**回滚与通知 (V10.1)**：
- **SEMI 模式回滚**：下单后 30 分钟通过 Telegram 提供撤销链接，Token 存储在缓存中。
- **止损修改**：Copilot 可通过 `modify_stop_loss` API 直接修改实盘止损。

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

### 4.2 Dashboard V2 Service (Performance Optimized)

**核心功能**：聚合全平台数据，构建实时仪表盘，并提供持仓/宏观评估。映射至 `position_macro.py`。

**V10.1 性能优化关键项**：
- **2秒极速响应**：通过 `asyncio.gather` 实现多标的技术分析与评分的全面并行化。
- **三级缓存策略 (Redis)**：
  - 账户概览：60秒 TTL。
  - 宏观分析风险水位：1小时 TTL。
  - 持仓技术评分：10分钟 TTL。
- **数据脱虚向实**：
  - 调用 `var_calculator.py` 计算真实 95% VaR。
  - 实时聚合 `algo_execution_tasks` 计算日内实盘/模拟盘滑点。

**并行实现模式**：
```python
async def get_positions_assessment():
    # 1. 全量标的评分并行化 (PositionScoringService.get_all_position_scores)
    # 2. 存量标的技术快照并行化 (asyncio.gather(process_symbol_tasks))
    # 3. 错误隔离策略 (return_exceptions=True)
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
    
  async def check(self, account_id: str, symbol: str, qty: float, side: str, signal_intent: str = "OPEN") -> RiskGateResult:
        """
        1. 计算执行后持仓权重 → 超过 MAX_SINGLE_POSITION_PCT 则拒绝
    2. OPEN 类信号运行 VaR@95% / 压力测试；REDUCE/EXIT 自动豁免
    3. OPEN 类信号检查当日已执行笔数；REDUCE/EXIT 不占用 MAX_DAILY_TRADES
    4. 检查当日已实现亏损 → 超过 MAX_DAILY_LOSS_PCT 时，仅阻止新增风险
    5. `ALLOW_CLOSING_DURING_CIRCUIT_BREAKER=true` 时，熔断期间允许平仓并写入 bypass_reason
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
        # 1. 组合级上下文准备 (V10.1: 聚合 signals + positions + optimized_weights)
        portfolio_ctx = await portfolio_optimizer.get_current_state(account_id)
        signals = await strategy_service.get_pending_signals(account_id)
        
        # 2. 调用 AI 批量决策 (Portfolio-Level Prompting)
        # V10.1: 一次性决定所有信号的执行比例，避免单一标的盲目性
        decisions = await self._ai_portfolio_decide(signals, portfolio_ctx)
        
        for decision in decisions:
          # 3. 执行路径分流（V10.4.3）
          #    STANDARD   = ENTRY / ADD
          #    FAST_CLOSE = REDUCE / EXIT
          #    FORCE_EXIT = PositionMonitor 止损/止盈触发
          gate = await risk_gate.check(
            account_id,
            decision.symbol,
            decision.qty,
            decision.action,
            signal_intent=decision.signal_intent,
          )
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

#### BacktestRunner — 事件驱动回测与自动毕业验证 (V10.1)

```python
class BacktestRunner:
    async def run(self, task: BacktestTask) -> dict:
        """
        1. OHLCV 加载 (DataHub) 2. bar 驱动 3. 模拟撮合 (Tiger API 实时滑点模拟)。
        4. 若 walk_forward=True，滚动窗口 in-sample/out-of-sample 验证
        5. 计算绩效指标：Sharpe / Sortino / MaxDrawdown / WinRate / Alpha
        """

    async def _check_graduation(self, task_result: dict) -> bool:
        """
        毕业红线检查：
        - Sharpe Ratio > 1.2 (过去 30 天)
        - Win Rate > 55%
        - Max Drawdown < 5%
        满足后：Paper -> Live 自动升级
        """

#### PaperTradingService — 模拟账户与毕业管理 (V10.1)

```python
class PaperTradingService:
    """管理 Paper 账户生命周期，并在 V10.1 执行 'Paper-to-Live' 自动毕业流程"""

    async def get_graduation_candidates(self) -> List[Strategy]:
        """识别已盘中模拟运行 30 天且收益达标的策略"""

    async def graduate_to_live(self, strategy_id: int):
        """升级策略：切换 order_executor 指向 Tiger OpenAPI"""
```
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

#### CopilotService — 对话式 AI 助理与意图执行

```python
class CopilotService:
    async def chat(self, account_id: str, session_id: str, message: str) -> CopilotResponse:
        """
        1. 轻量查询 → deepseek-chat/gpt-4o-mini（历史、状态查询）
        2. 复杂分析/操作意图 → deepseek-reasoner/gpt-5.2 (V10.1: 逻辑推理)
        3. 意图检测规则：
           - MODIFY_STOP-LOSS 意图 -> 映射至 order_service.modify_stop_loss
           - SUBMIT_TWAP/VWAP 意图 -> 映射至 twap_vwap_service.submit
           - CLOSE_ALL_POSITIONS 意图 -> 映射至 position_service.close_all
        4. 确认流程：返回 action_intent -> 前端确认 -> confirm_action 实际调用执行 API。
        """
```

**V10.1 意图指令落地表**：

| 意图代码 | 触发 API | 支持场景 |
|---------|---------|---------|
| `MODIFY_STOP` | `order_service.modify_stop_loss` | 降低/提高实盘止损位 |
| `SUBMIT_ALGO` | `twap_vwap_service.submit` | 美股/港股大单批量成交 |
| `LIQUIDATE` | `position_service.close_all` | 紧急清仓 |
| `HEDGE` | `auto_hedge_engine.activate` | 按 Delta 自动调整对冲 |

```python
    async def morning_brief(self, account_id: str) -> str:
        """
        每日 08:30 (盘前) 与 22:30 (美股开盘前) 生成。
        V10.1 性能优化实现 (<2s)：
        - Redis 4h 强缓存映射。
        - Tiered Model Routing: 默认使用 AI_LIGHTWEIGHT_MODEL。
        - 分析任务后台化，不阻塞主线程。
        """
```

---

### 4.6 V10.2-M2~M7 新增服务设计

#### EventCalendarService — 事件日历同步

```python
class EventCalendarService:
    """
    每日 07:00 ET 同步：
    - yfinance.Ticker.calendar → EARNINGS 事件（未来 14 天内活跃标的）
    - 硬编码 FOMC/CPI/NFP 2025 全年日期（高影响力宏观事件）
    写入 EventCalendarEntry，触发 EventBus.publish(Topic.EVENT_CALENDAR_UPDATED)
    """
    async def sync_earnings(self, symbols: List[str], lookahead_days: int = 14)
    async def get_calendar(self, lookahead_days: int, symbol: Optional[str]) -> List[EventCalendarEntry]
```

#### EarningsFenceService — 盈利围栏

```python
class EarningsFenceService:
    """
    PREEARNING_DAYS=1（盈利前1天激活围栏，默认）
    围栏激活时：新建仓/加仓数量上限 = 50% × 正常仓位
    订阅 EventBus.Topic.EVENT_CALENDAR_UPDATED 自动刷新
    """
    async def get_fence_status(self, symbol: str) -> FenceStatus
    async def get_all_active_fences(self) -> List[FenceStatus]
    async def override_fence(self, event_id: int, active: bool, reason: str)
```

#### DynamicPositionService — 动态仓位生命周期

```python
class PositionStateMachine:
    """
    状态机：INITIAL → PARTIAL → FULL → REDUCING → CLOSED
    三类引擎：
    - ScaleInEngine：盈利回调 > 30% 波动率 * ATR 时触发加仓
    - ScaleOutEngine：盈利超目标 1.5× 时分批减仓
    - TrailingStopEngine：移动止损（Price - N*ATR），ATR=14日
    """
    async def evaluate(self, ctx: PositionContext) -> LifecycleDecision
    async def get_scale_in_candidates(self, account_id: str) -> List[ScaleInCandidate]
```

#### SignalFusionEngine — 六维信号融合

```python
class SignalFusionEngine:
    """
    六维权重（基础）：
    - tech: 0.25（技术面/趋势/动量）
    - fundamental: 0.20（基本面/估值）
    - macro: 0.15（宏观风险/利率）
    - volatility: 0.15（波动率/VIX）
    - options: 0.15（期权链信号）
    - sentiment: 0.10（情绪/新闻）
    
    体制倍数：BULL_TREND tech×1.3 / CRISIS macro×1.5...
    composite_score = Σ(dim_score * effective_weight)
    """
    async def fuse(self, req: FusedSignalRequest) -> FusedSignalResponse
    async def get_sentiment_score(self, symbol: str) -> SentimentScoreResponse
```

#### TradeAttributionEngine — 三层交易归因

```python
class TradeAttributionEngine:
    """
    Layer 1 — Alpha 源归因：
        alpha_pnl = total_pnl * alpha_contribution_ratio
        contribution_ratio 由 signal_fusion 维度权重反推
    Layer 2 — 执行质量归因：
        exec_pnl = (actual_fill - theoretical_price) * qty
        exec_quality_score = 100 * (1 - |slippage_bps| / 50)
    Layer 3 — 仓位管理归因：
        pos_mgmt_pnl = scale_in_gain + trailing_stop_savings
    """
    async def attribute_trade(self, trade_id: str) -> TradeAttributionEntry
    async def get_attribution_summary(self, account_id: str, days: int) -> AttributionSummary
```

#### InsightService + ABTestEngine — AI 洞察进化

```python
class WeeklyInsightGenerator:
    """
    每周日 22:00 ET 使用 deepseek-reasoner 生成洞察：
    1. 聚合过去7天 trade_attribution_entries
    2. 识别 Alpha 源、执行模式、仓位管理规律
    3. 生成 WEEKLY_SUMMARY + LESSON 类型洞察写入 ai_insight_repository
    """

class ABTestEngine:
    """
    每日 08:00 检验运行中实验：
    使用 scipy.stats.ttest_ind 对 control/test 样本执行双样本 t-test
    p < 0.05 → 自动更新 statistical_significance=True 并写入 conclusion
    """
    async def run_significance_check(self, experiment_id: int)
```

#### CopilotPartnerService — Copilot Partner & 深度研究

```python
class DeepResearchEngine:
    """
    多步深度研究（POST /api/v1/copilot/deep-research）：
    Step 1: 市场情绪分析（deepseek-chat）
    Step 2: 基本面深潜（deepseek-reasoner）
    Step 3: 风险因素扫描（deepseek-chat）
    Step 4: 综合评级与价格目标（deepseek-reasoner）
    返回 DeepResearchReport{rating/price_target/body/sources}
    """
    async def research(self, symbol: str, query: Optional[str]) -> DeepResearchReport

class ProactiveIntelligenceService:
    """
    主动推送：订阅 EventBus 所有 Topic，当重大事件触发时
    通过 Telegram/Copilot 主动推送摘要（不等用户问）
    """
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

# V10.2-M1: 每日体制分类
scheduler.add_job(
    regime_classification_job,
    trigger="cron",
    hour=8,
    minute=0,
    id="daily_regime_classification"
)

# V10.2-M2: 每日事件日历同步
scheduler.add_job(
    sync_event_calendar_job,
    trigger="cron",
    hour=7,
    minute=0,
    id="daily_event_calendar_sync"
)

# V10.2-M6: 每周日洞察生成（美东 22:00）
scheduler.add_job(
    generate_weekly_insights_job,
    trigger="cron",
    day_of_week="sun",
    hour=22,
    minute=0,
    timezone="America/New_York",
    id="weekly_insight_generation"
)

# V10.2-M6: 每日 A/B 实验检验
scheduler.add_job(
    run_ab_significance_check_job,
    trigger="cron",
    hour=8,
    minute=30,
    id="daily_ab_significance_check"
)
```

| Job ID | 触发时间 | 说明 | 版本 |
|--------|---------|------|------|
| `daily_equity_snapshot` | 每日 00:05 | 权益快照 | V10 |
| `daily_performance_evaluation` | 每日 00:30 | 性能评估 | V10 |
| `refresh_technical_indicators` | 每小时 | 技术指标刷新 | V10 |
| `daily_regime_classification` | 每日 08:00 ET | 市场体制分类 | V10.2-M1 |
| `daily_event_calendar_sync` | 每日 07:00 ET | 事件日历同步（yfinance 盈利 + FOMC/CPI/NFP） | V10.2-M2 |
| `weekly_insight_generation` | 每周日 22:00 ET | AI 洞察生成（deepseek-reasoner） | V10.2-M6 |
| `daily_ab_significance_check` | 每日 08:30 | A/B 实验 t-test 检验 | V10.2-M6 |

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
  - 宏观分析概览：1 小时（性能优化版）
  - 持仓评估（综合版）：10 分钟（并行优化版）
  - 早间简报：4 小时（带模型动态切换）
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

### 11.2.1 System Monitor 增强（V10.4.3 追加需求）

**目标**：在现有 API/健康检查监控之外，补齐交易系统内部链路的“阶段、流转、服务”三级可观测性。

**监控域**：

- **交易生命周期状态**：基于 `autonomous_execution_intent`、Plan FSM、Position FSM 聚合 17 阶段分布、异常跳转、stuck intents、P95 阶段耗时
- **主要数据流转状态**：覆盖 `DataHub → Signal Generation/Fusion → Portfolio Decision → RiskGate → Execution → Position Monitor → Attribution/Post-Mortem`，对每个节点输出 `heartbeat / lag_seconds / queue_depth / last_success_at / last_error`
- **模块与细粒度服务状态**：按模块树输出 `Infrastructure / Market Data / Autonomy / Execution / Observability` 下的服务状态，统一状态枚举为 `HEALTHY / WARN / CRITICAL / UNKNOWN`

**建议接口**：

- GET `/api/v1/system-monitor/lifecycle`
- GET `/api/v1/system-monitor/lifecycle/{intent_id}`
- GET `/api/v1/system-monitor/data-flows`
- GET `/api/v1/system-monitor/data-flows/{flow_name}`
- GET `/api/v1/system-monitor/services`
- GET `/api/v1/system-monitor/services/{service_name}`

**状态聚合规则**：

- `HEALTHY`：心跳正常、无积压、无连续错误
- `WARN`：存在延迟升高、轻微积压或进入降级模式
- `CRITICAL`：心跳丢失、队列阻塞、连续错误超阈值或核心依赖不可用
- `UNKNOWN`：冷启动或当前采集数据不足

**契约文件（定稿）**：

- 后端 Pydantic：`app/schemas/system_monitor.py`
- 前端 TypeScript：`src/types/systemMonitor.ts`

**后端响应模型建议映射**：

- `/system-monitor/lifecycle` → `LifecycleOverviewResponse`
- `/system-monitor/lifecycle/{intent_id}` → `LifecycleIntentDetailResponse`
- `/system-monitor/data-flows` → `DataFlowOverviewResponse`
- `/system-monitor/data-flows/{flow_name}` → `DataFlowDetailResponse`
- `/system-monitor/services` → `ServiceOverviewResponse`
- `/system-monitor/services/{service_name}` → `ServiceDetailResponse`

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

---

## §10. V10.3 交易可观测性（Trade Observability）

> **V10.3 变更摘要**：新增交易生命周期中心（17 阶段 Pipeline Kanban + 双状态机面板 + 决策溯源抽屉）、智能订单簿（16 列高密度交易列表，3 分组视图）、态势感知条（全局 36px 粘性状态栏，WebSocket 实时推送）。新增约束：`trading_plan` 表扩充 10 个字段，新建 `fsm_transition_log` 表，3 个新增 Router/Service/Schema 模块，1 个 WebSocket 推送通道。

### 10.1 架构变更概览

```
V10.3 新增模块
───────────────────────────────────────────────────────────────────────
  app/schemas/
    lifecycle.py             ← Pipeline 聚合、FSM 状态、事件流、溯源 schema
    order_book.py            ← 智能订单簿列表、过滤器、汇总 schema
    situational_awareness.py ← 全局态势感知快照 schema

  app/services/
    lifecycle_service.py     ← 17 阶段分布聚合、FSM 计数、事件流查询、溯源链组装
    order_book_service.py    ← 订单列表聚合（含 plan_tags 解包）、止损修改
    situational_awareness_service.py  ← 6 数据块聚合（体制/VaR/围栏/执行/待确认/自主级别）

  app/routers/
    lifecycle.py             ← GET /api/v1/lifecycle/* (5 端点)
    order_book.py            ← GET/PATCH /api/v1/order-book/* (4 端点)
    websocket.py [修改]      ← 追加 WS /api/v1/ws/situational-awareness

  scripts/migrations/
    upgrade_to_v10_3.py      ← trading_plan 表新增 10 列 + fsm_transition_log 新表
───────────────────────────────────────────────────────────────────────
```

### 10.2 数据模型变更

#### trading_plan 表扩充列（ALTER TABLE）

| 列名 | 类型 | 说明 |
|------|------|------|
| `direction` | VARCHAR(4) | 交易方向：BUY / SELL |
| `confidence` | DECIMAL(5,2) | AI 综合置信度 0-100 |
| `reasoning` | TEXT | AI 决策摘要（最多 500 字） |
| `autonomy_action` | VARCHAR(20) | AUTO_EXECUTE / PENDING_CONFIRM |
| `source` | VARCHAR(20) | AI_AUTONOMOUS / AI_ADVISORY / MANUAL |
| `pipeline_stage` | SMALLINT | 当前所处 17 阶段（0-16） |
| `stage_entered_at` | DATETIME | 进入当前阶段的时间戳 |
| `stage_history` | JSON | `[{stage, entered_at, exited_at}]` |
| `provenance_snapshot` | JSON | `{six_dim_scores, regime, risk_gate_results, exec_progress}` |
| `position_fsm_state` | VARCHAR(20) | 关联持仓 FSM 最新状态 |

#### 新建表 fsm_transition_log

```sql
CREATE TABLE fsm_transition_log (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    plan_id        INT          NOT NULL,
    fsm_type       VARCHAR(10)  NOT NULL,  -- PLAN / POSITION
    from_state     VARCHAR(32),
    to_state       VARCHAR(32)  NOT NULL,
    engine         VARCHAR(32),            -- scale_in / scale_out / trailing / manual
    qty_delta      DECIMAL(10,4),
    trigger_reason TEXT,
    occurred_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fsm_plan_id (plan_id),
    INDEX idx_fsm_occurred_at (occurred_at)
)
```

### 10.3 API 端点

#### Lifecycle Router（`/api/v1/lifecycle`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/pipeline` | 17 阶段 Pipeline 任务分布 |
| GET | `/plan-fsm` | Plan FSM 各状态计数 |
| GET | `/position-fsm` | Position FSM 状态计数 + 引擎触发统计 |
| GET | `/fsm-events` | FSM 转换事件流（分页，?page&size&fsm_type） |
| GET | `/provenance/{plan_id}` | 单笔交易决策溯源链（5 卡片） |

#### Order Book Router（`/api/v1/order-book`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 全量订单视图（含过滤参数） |
| GET | `/summary` | 聚合汇总（数量/PnL/平均 confidence） |
| GET | `/{plan_id}/detail` | 单笔订单完整详情 |
| PATCH | `/{plan_id}/stop-loss` | 修改止损价 |

#### WebSocket 推送

| 路径 | 推送触发条件 | Payload 示例 |
|------|------------|-------------|
| `/api/v1/ws/situational-awareness` | 任意以下状态变化：体制 / VaR / 围栏数 / 执行数 / 待确认数 / 自主级别 | `{"type":"sa_update","data":{...}}` |

REST 轮询备用：`GET /api/v1/situational-awareness`（5 秒间隔）

### 10.4 Pipeline 阶段定义

| Stage | 名称 | 描述 | P50 基准 |
|-------|------|------|---------|
| 0 | regime_detect | 体制分类（RegimeClassifier） | ≤60s |
| 1 | signal_fusion | 六维信号融合（SignalFusionEngine） | ≤30s |
| 2 | strategy_match | 策略匹配（StrategyWeightAllocator） | ≤10s |
| 3 | plan_generation | AI 计划生成 | ≤120s |
| 4 | risk_gate | 风险门控（RiskGateService 5 项检查） | ≤5s |
| 5 | autonomy_decision | 自主决策路由（FULL/SEMI/ADVISORY） | ≤5s |
| 6 | human_review | 人工审核等待（SEMI 模式） | ≤300s |
| 7 | order_placement | 下单（broker 层）| ≤10s |
| 8 | algo_execution | 算法执行（TWAP/VWAP） | ≤3600s |
| 9 | position_monitor | 持仓监控（PositionStateMachine） | 持续 |
| 10 | scale_adjust | 加减仓调整（ScaleIn/Out/Trailing） | ≤60s |
| 11 | exit_trigger | 离场触发（目标价/止损/过期） | ≤30s |
| 12 | settlement | 订单结算 | ≤60s |
| 13 | attribution | 归因分析（TradeAttributionEngine） | ≤120s |
| 14 | insight_update | 经验库更新（InsightService） | ≤300s |
| 15 | ab_experiment | A/B 实验登记 | ≤60s |
| 16 | completed | 交易完成存档 | — |

### 10.5 服务层职责划分

```
LifecycleService
  ├── get_pipeline_distribution()     — 查 trading_plan 按 pipeline_stage 分组 COUNT
  ├── get_plan_fsm_counts()           — 查 trading_plan 按 plan_status 分组
  ├── get_position_fsm_counts()       — 查 trading_plan 按 position_fsm_state 分组
  ├── get_fsm_events(page, size, fsm_type) — 查 fsm_transition_log 分页
  └── get_provenance(plan_id)         — 组装 5 卡片溯源数据

OrderBookService
  ├── list_orders(filters)            — 聚合 trading_plan + plan_tags 解包 + 分组
  ├── get_summary()                   — 数量/PnL/均 confidence
  ├── get_order_detail(plan_id)       — 单笔完整详情（含 provenance_snapshot）
  └── update_stop_loss(plan_id, price) — PATCH 止损，写 fsm_transition_log

SituationalAwarenessService
  ├── get_snapshot()                  — 聚合 6 数据块（一次 DB + Redis 查询）
  └── _should_push(prev, cur)         — 变更检测，决定是否 WS 广播
```

### 10.6 性能策略

| 场景 | 策略 |
|------|------|
| Pipeline 分布轮询 | Redis 缓存 5s，TTL 到期后惰性刷新 |

---

## §11. V10.4.1 — 数据闭环治理 & 系统稳定增强（M1 / M3 / M4）

### 11.1 M1：数据闭环治理（Data Loop Governance）

#### 11.1.1 ReturnBackfillJob（T1.1）

**背景**：`TradingSignal.actual_return` 需要在持仓平仓后从成交数据回填，此前仅有手动脚本，未集成进 APScheduler。

**实现**：新增 `app/jobs/m1_data_loop_jobs.py`，注册 `return_backfill_job`：

```python
# 调度配置
trigger: CronTrigger
hour=21, minute=30           # 每日 21:30（本地 / ET 由部署 TZ 决定）
id="m1_return_backfill"
```

**回填逻辑**（`ReturnBackfillService`）：

```
SELECT ts JOIN tj ON ts.signal_id = tj.signal_id
  WHERE ts.actual_return IS NULL
    AND tj.exit_price IS NOT NULL
    AND tj.journal_status = 'CLOSED'
UPDATE ts SET actual_return = (exit_price - entry_price) / entry_price
             pnl_pct = realized_pnl / (qty * entry_price)
```

- 回填完成且新增 ≥10 条后，异步触发 `SignalIntelligenceService.recompute_ic_for_all_users()`
- 写入 `scheduler_run_log`（job_id + rows_updated + duration_ms）

**验收**：已平仓信号 actual_return 非 null 率 ≥95%，每日日志可查。

#### 11.1.2 IC 数据质量字段（T1.2）

`SignalIntelligenceService.compute_dimension_ic()` 返回值新增 `data_quality` 字段：

| 值 | 触发条件 |
|----|---------|
| `REAL` | `sample_source = "trading_signals"` 且样本量 ≥10 |
| `INSUFFICIENT` | 样本量 < 10 |
| `STALE` | 最近一次 computed_at 距今 > 7 天 |

**变更**：
- 移除 `expected_return` 作为代理收益（之前冷启动场景使用，会造成自相关偏差）
- 当 `data_quality != REAL` 时，`ic_5d/ic_20d/ic_60d` 仍返回（来自 weight_history fallback），但前端应展示数据质量状态而非原始曲线

#### 11.1.3 因子快照零值处理（T1.3）

`observability_jobs.take_factor_exposure_snapshot()` 增强：
- 无活跃持仓用户也写入 `positions_count=0` 快照（之前直接返回跳过）
- 从 `TradingPlan` 扫描所有有历史活跃仓位的用户，而非仅当前活跃

#### 11.1.4 LLMCallGuard（T1.5）

新增 `LLMCallGuard` 上下文管理器，封装所有 LLM 调用：

```python
class LLMCallGuard:
    timeout_seconds: int = 30
    max_retries: int = 3
    base_retry_delay: float = 1.0  # 指数退避基础延迟
    
    async def call(self, fn, *args, **kwargs) -> LLMCallResult:
        # 超时保护：asyncio.wait_for(fn(), timeout)
        # 重试策略：429/5xx 指数退避，最多3次
        # 降级返回：超时/耗尽重试 → LLMCallResult(degraded=True, fallback_reason=...)
        # 写日志：llm_call_log 每次调用
```

新增 `LlmCallLog` 数据库模型（`app/models/llm_call_log.py`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT AUTO_INCREMENT | 主键 |
| `call_id` | VARCHAR(36) | UUID |
| `caller` | VARCHAR(64) | 调用方服务名 |
| `model` | VARCHAR(64) | 使用的模型 |
| `prompt_tokens` | INT | 输入 token 数 |
| `completion_tokens` | INT | 输出 token 数 |
| `latency_ms` | INT | 调用耗时 |
| `status` | VARCHAR(16) | SUCCESS/TIMEOUT/RATE_LIMITED/ERROR |
| `degraded` | BOOL | 是否降级响应 |
| `error_msg` | TEXT | 错误信息（可 null）|
| `created_at` | DATETIME | 调用时间 |

新增 API 端点：`GET /api/v1/api-monitoring/llm-stats`，返回近 24h 成功率、P95 延迟、总 token 消耗。

### 11.2 M3：Copilot 系统上下文服务

新增 `GET /api/v1/copilot/context` 端点，返回供浮层注入的系统快照：

```json
{
  "page_context": {},
  "system_state": {
    "autonomy_level": "SEMI",
    "regime": "BULL_TREND",
    "regime_confidence": 85,
    "var_pct": 1.9,
    "var_limit_pct": 3.0,
    "active_position_count": 7,
    "total_unrealized_pnl": 3420.5,
    "executed_today": 3,
    "success_rate_today": 100,
    "latest_alert_summary": "MSFT 明日财报，围栏已激活"
  },
  "quick_actions": [
    "盘前摘要", "今日复盘", "持仓概况"
  ]
}
```

### 11.3 M4：自主循环稳定增强

#### 11.3.1 AutonomyHealthMonitorService

新增 `app/services/autonomy_health_monitor.py`，每 10 分钟执行 8 项健康自检：

| 检查项 | 阈值 | 告警级别 |
|--------|------|---------|
| Scheduler 心跳 | 最近 15 分钟内有 Job 运行 | CRITICAL |
| DB 连接池可用 | pool.size - pool.checkedout > 0 | CRITICAL |
| actual_return 回填率 | 近7日 ≥80% | HIGH |
| LLM 调用成功率 | 近1h ≥90% | HIGH |
| Factor Snapshot 时效 | 距今 ≤ 30 分钟 | MEDIUM |
| WebSocket 连接数 | ≥1（有活跃前端） | LOW |
| Redis 可达 | ping 延迟 < 100ms | HIGH |
| 执行队列无堆积 | pending intent < 20 | MEDIUM |

结果写入 `system_health_snapshot`（已有表），`status` 字段值：`HEALTHY`/`DEGRADED`/`CRITICAL`。

#### 11.3.2 JobWatchdog

新增 `JobWatchdogService`，每 5 分钟检查关键 Job 的上次运行时间：

```python
WATCHED_JOBS = {
    "observability_factor_snapshot": {"interval_minutes": 5, "tolerance": 2.0},
    "m1_return_backfill":           {"interval_minutes": 1440, "tolerance": 1.5},
    "regime_classify_daily":        {"interval_minutes": 1440, "tolerance": 1.5},
    "ai_hub_calibration_snapshot":  {"interval_minutes": 1440, "tolerance": 1.5},
}
# tolerance: 允许超时 interval * tolerance 倍，超出则重新触发补跑
```

### 11.4 新增 DB 表汇总（V10.4.1）

| 表名 | 用途 | 迁移脚本 |
|------|------|---------|
| `llm_call_log` | LLM 调用全量记录 | `upgrade_to_v10_4_1.py` |

### 11.5 新增 API 端点汇总（V10.4.1）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/copilot/context` | GET | Copilot 浮层系统上下文 |
| `/api/v1/api-monitoring/llm-stats` | GET | LLM 调用统计（近24h）|
| `/api/v1/admin/health/autonomy` | GET | 自主循环健康状态 |
| `/api/v1/admin/health/watchdog` | GET | Job Watchdog 状态 |

| 态势感知快照 | Redis 缓存 3s + WS 推送减少轮询 |
| FSM 事件流 | 分页 20条/页，`occurred_at DESC` 索引覆盖 |
| 订单簿列表 | 复合 WHERE + LIMIT，最多返回 500 条 |
