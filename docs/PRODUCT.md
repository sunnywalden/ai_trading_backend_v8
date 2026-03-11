# 产品需求文档 (PRD)

> ⚠️ **V10.4.1 M6 文档拆分通知**
> 本文档已拆分为模块化子文档，位于 [`docs/product/`](product/README.md)。
> 本文件保留作为向后兼容入口，正式维护请在 `docs/product/` 目录进行。
> **AI量化交易闭环系统** - 个人美港股智能交易平台  
> 版本：V10.5.4（规划中）| 当前已上线版本：V10.5.2 | 更新日期：2026-03-11  
> 变更摘要（V10.5.4 规划）：**Signal Pipeline Integrity & Control-Plane Hardening**——本版本先收敛信号控制平面，再继续推进 Profit Engine：围绕 **Signal Discovery Integrity**（REAL / SYNTHETIC / BACKFILL 真源区分）、**Canonical Signal Payload & State Machine**（统一 payload、原生状态迁移、恢复语义）、**Autonomous Control Plane Hardening**（统一自动执行主链、统一 positions / regime / audit 真源、席位置换完整闭环）、**Native Audit & Governance Discipline**（Watchtower 原生审计优先、完整开发流程、Observe → Shadow → Semi → Full 放量纪律）四条主线推进，目标是在不放宽风险上限的前提下，把信号发现、状态、执行与审计口径统一成可验证、可回退、可放量的交易控制平面。  
> 变更摘要（V10.5.2 交付）：**组合席位竞争引擎（Capacity-Aware Admission & Replacement Engine）**——把「持仓上限」从刚性拒绝规则升级为动态席位分配机制：新增 **Unified Candidate Pool**（当前持仓 + 新信号统一候选池）+ **统一准入评分** `admission_score = alpha_quality - replacement_friction - risk_penalty + regime_fit`，满仓时按分数淘汰末位 N 个对象（持仓→EXIT、信号→REJECTED_BY_CAPACITY_REPLACEMENT）；引入替换保护带（`MIN_REPLACEMENT_EDGE_BPS / MAX_REPLACEMENTS_PER_CYCLE / MIN_HOLD_MINUTES / REPLACEMENT_COOLDOWN_MINUTES`）防止过度翻仓；**Incumbent Decay Model** 让持仓持续参与席位竞争（alpha 衰减 + 体制适配 + 机会成本）；新增 `capacity_decision_audit_log` 全量审计；支持 `CAPACITY_REPLACEMENT_DRY_RUN` 先观测再放量；前端 `/portfolio`、`/autonomy`、`/order-book` 增加「席位竞争结果」可视化。  
> 变更摘要（V10.5.1 交付）：**从“功能完整”走向“机构级交易操作系统”**——下一版本不再以新增页面和策略数量为核心，而聚焦三条机构级主线：**Alpha Truth Stack**（策略净 alpha、信号衰减、影子组合、Purged Walk-Forward、成本后真实表现）、**Portfolio Construction 2.0**（风险预算树、流动性感知仓位、边际风险/alpha/turnover 贡献）、**Execution Policy Engine**（订单紧急度、参与率、滑点预算、预交易成本模型、成交后回放）；同时补齐 **Live Safety & Model Degradation Guard**（模型退化监控、数据新鲜度 kill matrix、自主度自适应降级）与 **Research-to-Live Governance**（shadow live、晋级流水线、实验总账），让平台从“能跑的自主交易系统”升级为“可验证、可控放量、可持续进化的研究与交易一体化系统”。【补丁交付】：事后决策剪析自动化（Post-Mortem Automation）——新增 `post_mortem_jobs.py`，通过 EventBus 订阅 `Topics.POSITION_CLOSED` 实时触发 + 每日 02:00 UTC 岜底 Cron 扫描近 90 天未剪析平仓仓位，幂等排队 `deepseek-reasoner` 生成结构化复盘（`trade_id="position-{id}"`），`_RUNNING_TASKS` 集合防 GC；事件日历数据新鲜度修复——`data_freshness_guard_service.py` 改查 `EventCalendarEntry.updated_at`（原 `created_at`），`event_calendar_service.py` upsert 时对已存在记录刷新 `updated_at`，消除 `event_calendar` 83h 陈旧 WARN。  
> 变更摘要（V10.4.3）：**风险降低优先执行（Risk-Reducing Priority Execution）**——新增减仓/平仓快速通道：`REDUCE/EXIT` 信号绕过开仓型质量漏斗、熔断期间允许风险降低类订单、减仓/平仓不占用 `MAX_DAILY_TRADES` / `MAX_DAILY_SIGNALS` 配额；`PositionMonitor`止损/止盈信号写入 `force_exit=true`，`AutonomousEngine` 识别后跳过冷却与 Redis 并发锁直接执行；`SignalPositionFilter` 在减仓数量超持仓时自动升级为全平；`OrderExecutor` 以实际持仓数量为准执行 EXIT/REDUCE，并为港股退出保留 odd-lot 平仓能力；`AutonomyPage` 新增“减仓/平仓优先通道”状态卡与快速通道/强制出场徽章。**补充**：开仓型信号新增 `LOW / MEDIUM / HIGH / ELITE` 质量标识，进入漏斗前先按质量排队；其中 `ELITE` 信号可豁免 `SQ_MAX_DAILY_SIGNALS` 日配额上限，但仍必须通过仓位、相关性与 RiskGate。**追加需求**：`/system` 系统监控模块需新增交易生命周期状态监测、系统主要数据流转详细状态、系统主要模块及细粒度服务状态。  
> 变更摘要（V10.4.4）：**以仓位为中心的生命周期治理 (Position-Centric Lifecycle)**——引入 `positions` 聚合根与 `execution_slices` 执行切片，支持多主题仓位隔离与 Append-Only 生命周期事件审计；`autonomous_execution_intent` 关联仓位与切片，实现从信号到仓位动作的全链路追踪。  
> 变更摘要（V10.4.2）：**信号精英化与幽灵交易 (Signal Conviction & Ghost Trades)**——上线信号品质漏斗审计日志 `signal_quality_audit_logs`，记录高置信度多维共振评估过程；新增 `ghost_trades` 幽灵交易机制，虚拟跟踪被拒信号的后续表现以校验门控有效性。  
> 变更摘要（V10.4.1）：**LLM 调用观测治理 (LLM Call Observability)**——上线 `llm_call_log` 全量日志表，记录调用方、延迟、Token 消耗、状态及降级标记，加强对 AI 服务稳定性的细粒度监控。  
> 变更摘要（V10.4）：**巩固、治理与完整性**——M1 数据闭环治理（actual_return 自动回填 Job + IC 真实化 + 因子快照自动化 + 2026 事件日历 + LLM 降级）；M2 UI 大清洗（47→≤38 页面 + 导航 6→4 组 + 执行三合一 + 双仪表盘合并）；M3 Copilot 全局浮窗（Cmd+K 任意页面唤起 + 页面上下文注入 + 实时系统状态 System Prompt）；M4 自主循环稳定增强（AutonomyHealthMonitor + Job Watchdog + Multi-Agent 真实并发 + 三新熔断 + WebSocket 重连）；M5 移动触达（Dashboard/Alert/Copilot 竖屏可用）；M6 文档重构（PRODUCT.md 拆分为模块化多文件，主文件 ≤300 行）  
> 变更摘要（V10.3.4）：**稳定性与冷启动治理（Stability & Cold-Start Governance）**——全服务冷启动双保险（Dashboard / 代理运行状态 / 执行质量记录 / 置信度校准补全零数据占位逻辑，消除前端 404 抖动）；**市场全量股票池（Market Universe Pool）**——新增 `market_universe` 表，支持美股/港股全量标的同步与缓存；**AI 决策深化**——自主引擎支持 REDUCE/EXIT 信号规则执行，`HOLD/qty≤0` 语义纠偏为 SKIPPED（no-op 原因落库），信号管道新增 `quantity_mode/quantity_value` 标准化；**决策事后剖析升级**——从手工录入升级为交易选择驱动；**多账户兼容**——告警/归因/仪表板接口统一账户 ID 解析；**事件去重**——事件表唯一索引 + 重复写入保护  
> 变更摘要（V10.3.3）：**P0 可观测性 2.0（Observability 2.0）**——Execution Microscope 执行显微镜（IS 成本四分解：迟延成本/市场冲击/机会成本/时机成本）+ Signal Intelligence Observatory 信号情报观察站（Alpha Decay Monitor 信号半衰期曲线 + Factor Correlation Matrix + Crowding Detector）+ Risk Observability Cluster（实时因子敞口条 + Tail Risk ES 仪表 + 相关性骤升告警）；**P1 AI中枢 2.0（AI Hub 2.0）**——Multi-Agent Orchestration 五智能体协作框架（市场分析 / 风险挑战 / 执行优化 / 深度研究 / Orchestrator 总协调）+ AI Confidence Calibration 置信度校准系统（Reliability Diagram + 自适应降评）+ Adaptive Factor Framework 自适应因子框架（Kalman Filter实时权重更新 + 因子拥挤度检测）+ Decision Post-Mortem Engine 决策事后剖析（反事实分析 + 洞察反哺 InsightService）；**P2 指挥室演进（War Room Dashboard）**——War Room Mode 全屏六格指挥视图 + real-time P&L Ticker + Intelligence Feed AI情报流 + Portfolio Exposure Center 组合敞口中枢 + Smart Alert Center 智能告警分级中枢
> 变更摘要（V10.3.2）：**P0 执行幂等主键（Execution Intent）**——新增 `autonomous_execution_intent` 表与 `idempotency_key` 唯一约束，确保同一信号同一动作只受理一次；**P1 统一执行入口强化**——`AutonomousEngine.run_decision_cycle` 内统一进入 execution-intent 状态机（PENDING/EXECUTING/SUCCESS/FAILED/SKIPPED/REJECTED），并补齐 RiskGate/CircuitBreaker 拒绝分支的 intent 落库；**P2 语义一致性升级**——交易信号新增 `quantity_mode + quantity_value`（`PCT_EQUITY` / `ABS_SHARES`）并在自主决策链路标准化解析，且补齐策略引擎/快捷交易/交易计划/持仓监控等入口写入，`HOLD/qty<=0` 由 `EXECUTED` 语义纠偏为 `SKIPPED`。
> 变更摘要（V10.3）：**交易全链路可观测性（Full Trade Observability）**——Trade Lifecycle Center（交易生命周期中枢）双维度可视化（计划生命周期状态机 + 持仓生命周期状态机）+ 实时甘特泳道图；**智能订单簿（Intelligent Order Book）**——统一交易列表（标的/方向/价位/17阶段进度/AI简述/实时P&L/风险标记），替代分散的 AI Advisor + Journal 孤岛视图；**AI 决策溯源面板（Decision Provenance）**——从原始信号到最终执行的完整因果链可视化；**系统态势感知栏（System Situational Awareness Bar）**——全局粘性状态栏，实时聚合体制/VaR水位/事件围栏/活跃阶段/执行队列等关键状态  
> 变更摘要（V10.2-M2~M8）：**事件驱动风控**——EventCalendarService 盈利/FOMC/CPI/NFP 日历同步 + EarningsFenceService 盈利围栏（盈利前1天50%仓位上限）；**动态仓位生命周期**——PositionStateMachine 三引擎（ScaleIn/ScaleOut/TrailingStop）；**信号融合**——SignalFusionEngine 六维加权评分（tech 25%/fundamental 20%/macro 15%/vol 15%/opt 15%/sentiment 10%）+ 体制倍数；**交易归因**——TradeAttributionEngine 三层分析（Alpha源/执行质量/仓位管理）+ AttributionPage 可视化；**AI 进化**——InsightService 自动周报（deepseek-reasoner Sunday 22:00 ET）+ ABTestEngine（scipy t-test p<0.05）+ EvolutionPage；**Copilot Partner**——DeepResearchEngine 多步深度研究 + ProactiveIntelligenceService 主动推送  
> 变更摘要（V10.2-M1）：**市场体制感知引擎** ——RegimeClassifier 五维评分体系（趋势强度/波动率制度/量价关系/宏观环境/广度指标）、6类体制自动识别（BULL_TREND / BEAR_TREND / HIGH_VOL / MEAN_REVERT / RANGE_BOUND / CRISIS）、3日确认防噪机制、EventBus 异步事件总线（REGIME_CHANGED 事件驱动策略权重自适应切换、VaR 门限动态调整）、StrategyWeightAllocator 体制感知仓位分配、AI 自主交易闭环升级至 **17 阶段**  
> 变更摘要（V10.1）：**兑现承诺 + 打磨质量 + 扩展边界**——Tiger 真实下单接入（覆盖美股/港股/期权）、FULL 模式完整自主交易闭环、Copilot 操作指令执行落地、Dashboard 所有 TODO 指标真实化、AI 组合级决策升级（结构化 JSON 输出 + 批量组合决策）、ETF 标的池正式支持、港股支持（Tiger API 统一，无需 Futu）、Paper→Live 毕业自动化、Dashboard WebSocket 实时推送；**本版本明确不含 Telegram 通知，FULL 模式具备完全自主交易能力**
> 历史版本：V10.0（2026-02-24）变更摘要见下方历史记录节  
> 当前已上线版本：**V10.5.2**（已发布）| 详细规划：[V10.5.2 Release Plan](archived/v10/v10.5/RELEASE_PLAN_V10.5.2.md)  
> 下一版本规划：**V10.5.4** | 详细规划：[V10.5.4 Release Plan](archived/v10/v10.5/RELEASE_PLAN_V10.5.4.md)

---

## V10.5.2 验收标准（已发布）

> 完整规划详见 [docs/archived/v10/v10.5/RELEASE_PLAN_V10.5.2.md](archived/v10/v10.5/RELEASE_PLAN_V10.5.2.md)

### P0 核心验收（已完成）

- [x] 当 `current_positions + incoming_signals > max_positions` 时，系统不再直接因满仓拒绝全部新信号
- [x] 系统可对当前持仓+新信号生成统一排序结果与 overflow 淘汰清单
- [x] 被淘汰持仓自动进入 `EXIT/FORCE_EXIT` 编排；被淘汰信号进入容量拒绝状态（`REJECTED_BY_CAPACITY_REPLACEMENT`）
- [x] 审计日志可展示每个对象的 `admission_score`、淘汰原因和保护带结果
- [x] 支持 `CAPACITY_REPLACEMENT_DRY_RUN` 模式，可先只观测不执行

### P1 验收（已完成）

- [x] 保护带、冷却期、每轮替换上限可通过环境变量配置
- [x] 前端 `/portfolio`、`/autonomy`、`/order-book` 可展示席位竞争结果与约束说明
- [x] `capacity_decision_audit_log` 全量落库，每次满仓准入决策可完整回放

---

## V10.5.4 验收标准（规划中）

> 完整规划详见 [docs/archived/v10/v10.5/RELEASE_PLAN_V10.5.4.md](archived/v10/v10.5/RELEASE_PLAN_V10.5.4.md)

### V10.5.4 开发流程（定稿）

- **第 1 阶段：文档对齐** —— `PRODUCT.md / FRONTEND_DESIGN.md / BACKEND_DESIGN.md / API.md` 四份主文档先统一版本口径、feature flags、rollout phases、legacy 路径与验收矩阵。
- **第 2 阶段：后端阻塞项** —— 先完成 `signal_origin_mode` 全链路、canonical signal payload、native state transition、AutonomousEngine 单主链收敛、positions / regime / audit 真源统一，以及 displacement pending 完整闭环，且全部支持 flag-gated rollout。
- **第 3 阶段：前端工作台升级** —— 仅升级现有工作台（`/alpha-lab`、`/portfolio`、`/execution-policy`、`/governance/pipeline`、`/autonomy`），不新增导航分组；所有关键结论必须同时给出“结果值 + 解释字段 + 数据质量 + 来源类型”。
- **第 4 阶段：测试与联调** —— 单元测试、集成测试、前后端联调、Cypress E2E 与产品验收并行推进，必须覆盖 REAL/SYNTHETIC 区分、native vs reconstructed audit、legacy path 不误接管生产链路。
- **第 5 阶段：渐进放量** —— 按 `Observe → Shadow → Semi → Full` 分四阶段放量，不允许 V10.5.4 直接默认硬切 live 链路。

### V10.5.4 Feature Flags（定稿）

- `SIGNAL_PIPELINE_V1054_ENABLED`：控制 canonical payload / origin mode / native transition log 是否进入主链。
- `AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED`：控制单主链收敛、legacy path 限制、统一自动执行编排是否接管。
- `NATIVE_AUDIT_V1054_ENABLED`：控制 Watchtower / signal pipeline 是否优先使用原生审计。
- `GOVERNANCE_HARD_GATE_ENABLED`：控制五阶段晋级与回滚门是否参与真实策略放量。
- `SEAT_VALUE_ARBITER_ENABLED`：控制 `CapacityArbiter` 是否在控制平面收敛后切换到 `SeatValue` 仲裁。
- `EXECUTION_POLICY_HARD_CONTROL_ENABLED`：控制 pre-trade cost / policy snapshot 是否进入真实执行决策，而不仅是观测视图。

### V10.5.4 Rollout 策略（定稿）

| 阶段 | 目标 | 规则 |
|------|------|------|
| Observe | 只观测，不接管 | 计算 canonical / native audit / truth sources，但不改变 live 行为 |
| Shadow | 影子接管 | 只在 shadow / paper 路径启用统一控制平面，记录与旧逻辑差异 |
| Semi | 半接管 | 对有限真实链路启用 unified control plane，并保留人工审计与快速回退 |
| Full | 全接管 | AutonomousEngine + native audit + governance hard gate 成为默认主链 |

### M1 — Signal Discovery Integrity

- [ ] 自动信号 100% 带 `signal_origin_mode`
- [ ] `SYNTHETIC` 信号默认不进入生产自动执行主链
- [ ] discovery 诊断面可观测 REAL / SYNTHETIC / BACKFILL 分布

### M2 — Canonical Payload & State Machine

- [ ] 新信号 100% 写 canonical payload
- [ ] Watchtower / Quality Funnel / CapacityArbiter / AutonomousEngine 优先读取 canonical payload
- [ ] 原生状态流转可完整回答任一信号为何被拒、为何执行、为何卡住

### M3 — Autonomous Control Plane Hardening

- [ ] 自动执行 100% 由 `AutonomousEngine.run_decision_cycle()` 编排
- [ ] positions / regime / audit 真源在 UI 与执行链中一致
- [ ] displacement pending → exit submitted → exit filled → entry released 可完整回放

### M4 — Native Audit & Governance Discipline

- [ ] Watchtower 默认优先显示 native audit，fallback 明确标记 `RECONSTRUCTED`
- [ ] 关键控制能力全部具备 flag + phase + rollback 能力
- [ ] `Discovery → Production` 的治理证据链可对接真实控制平面

## V10.4 验收标准（规划归档）

> 完整规划详见 [docs/archived/v10/v10.4/RELEASE_PLAN_V10.4.md](archived/v10/v10.4/RELEASE_PLAN_V10.4.md)

### M1 — 数据闭环治理

- [ ] `actual_return` 每日 21:30 ET 自动回填，已平仓信号回填率 ≥ 95%
- [ ] IC 计算无 hardcoded fallback，所有维度返回 `data_quality` 字段（`REAL`/`INSUFFICIENT`/`STALE`）
- [ ] `portfolio_factor_exposure` 快照每 5 分钟自动写入（交易时段），无需手动 seed
- [ ] 事件日历补全 2026 年 FOMC / CPI / NFP / PCE 全年数据
- [ ] 所有 LLM 调用通过 `LLMCallGuard` 包装，超时/429 不导致 500；`llm_call_log` 记录全量调用

#### M2 — UI 大清洗

- [ ] 前端页面总数 ≤ 38，路由总数 ≤ 40
- [ ] 废弃路由均有 301 重定向，无 404
- [ ] 导航一级分组 ≤ 4（重组为：首页仪表盘 / 交易中枢 / 研究&分析 / AI洞察&系统）
- [ ] DashboardPage + DashboardV2Page 合并为单页（`/dashboard`）
- [ ] 执行三页（ExecutionCenter/List/Algo）合并为 Order Book + Tab

#### M3 — Copilot 全局化

- [ ] 所有页面右下角 Copilot 浮按钮，`Cmd+K` 可唤起浮窗
- [ ] 5 个核心页面实现上下文注入（Dashboard/OrderBook/RiskCluster/WarRoom/Regime）
- [ ] Copilot System Prompt 包含实时系统状态注入（体制/VaR/持仓/告警摘要）

#### M4 — 自主循环稳定增强

- [ ] `AutonomyHealthMonitor` 每 10 分钟执行 8 项健康自检，结果写入 `system_health_snapshot`
- [ ] `JobWatchdog` 在 Job 超时 2× 预期间隔时自动重注册并补跑
- [ ] `MultiAgentOrchestrator` 在每次决策周期真实并发调用 5 Agent，`agent_communication_log` 可查
- [ ] WebSocket 前端指数退避重连（初始 1s，最大 30s），断线 ≤ 30s 恢复推送

#### M4.1 — 系统监控增强（追加需求）

- [ ] `/system` 支持交易生命周期监测：展示 17 阶段流水线滞留数、Plan/Position FSM 分布、异常跳转、`stuck_intents` 与最近失败阶段
- [ ] `/system` 支持系统主要数据流转详细状态：覆盖 `DataHub → Signal Generation/Fusion → Portfolio Decision → RiskGate → Execution → Position Monitor → Attribution/Post-Mortem`，展示 `heartbeat / last_success_at / lag_seconds / queue_depth / last_error`
- [ ] `/system` 支持主要模块及细粒度服务状态：按模块树展示 `DB / Redis / Tiger / LLM / Scheduler / WebSocket / Autonomy / Observability` 等核心模块及下钻服务的 `HEALTHY/WARN/CRITICAL/UNKNOWN` 状态、最近 24h 错误计数与降级标记

#### M5 — 移动触达

- [ ] Dashboard 在 375px 竖屏下无横向溢出，总 PnL / 活跃持仓 / VaR 水位可见
- [ ] Smart Alert 在 375px 下可滚动，可标记已读
- [ ] Copilot 浮层在 375px 下全宽，输入框固定底部

#### M7 — 风险降低优先执行（V10.4.3）

- [x] `REDUCE/EXIT` 信号默认走快速通道，不进入开仓型 `SignalQualityFunnel`
- [x] 熔断期间允许风险降低类订单，`RiskGateResult.details.bypass_reason=closing_intent`
- [x] 减仓/平仓不占用 `MAX_DAILY_TRADES` / `SQ_MAX_DAILY_SIGNALS` 配额
- [x] `PositionMonitor` 生成的止损/止盈信号写入 `force_exit=true`，执行时跳过冷却与 Redis 锁
- [x] `SignalPositionFilter` 对超持仓减仓自动升级为 `EXIT`
- [x] `OrderExecutor` 对 EXIT/REDUCE 使用实际持仓数量，港股 odd-lot 退出不再被一手限制阻断
- [x] `AutonomyPage` 展示快速通道 / 强制出场执行路径与当日风险出场指标
- [x] 开仓型信号新增 `LOW / MEDIUM / HIGH / ELITE` 质量标识，并按质量顺序进入漏斗
- [x] `ELITE` 精英级信号可越过 `SQ_MAX_DAILY_SIGNALS` 日配额限制，但不得绕过持仓/相关性/RiskGate

#### M6 — 文档重构

- [ ] `PRODUCT.md` 主文档 ≤ 300 行，拆分为 `product/0X_xxx.md` 9 个子文档
- [ ] `FRONTEND_DESIGN.md` 主文档 ≤ 400 行

---

### V10.3.4 验收标准（归档）

**稳定性与冷启动治理（已全部交付）**：

- [x] 全服务冷启动占位：Dashboard / Agent 运行状态 / 执行质量记录 / 置信度校准快照补全零数据返回逻辑，消除前端 404 抖动
- [x] `market_universe` 表上线，`MarketUniverseService` 支持美股/港股全量标的同步与缓存；`GET /api/v1/market-universe/status` 返回标的活跃状态及同步信息
- [x] 自主引擎支持 REDUCE/EXIT 信号规则执行；`HOLD/qty≤0` 语义纠偏为 SKIPPED（no-op 原因字段落库）
- [x] 事件表新增唯一索引 + 去重逻辑，防止重复事件写入
- [x] 多账户兼容性：告警 / 仪表板 / 归因 / 量化闭环接口统一账户 ID 解析
- [x] 决策事后剖析（Post-Mortem）从手工录入升级为交易选择驱动
- [x] 置信度校准快照支持原地更新与重复检测
- [x] DB 迁移：`v10.3.4_add_market_universe_table` 已执行

---

### V10.3.3 验收标准（归档）

#### 一、可观测性 2.0 (Observability 2.0)

**P0 — Execution Microscope（执行显微镜）**
- [x] `ExecutionMicroscopeService` 计算 Implementation Shortfall (IS) 四分解：`delay_cost + market_impact_cost + opportunity_cost + timing_cost`，每笔 intent 完成后写入 `execution_quality_log` 表。
- [x] `GET /api/v1/observability/execution-quality` 返回按时段/标的聚合的 Fill Rate、IS 分解、vs VWAP deviation 三组指标。
- [x] Dashboard 执行质量面板：Execution Alpha（到达价 vs 实际成交价）色码热力图，实时 P95 滑点数值。

**P1 — Signal Intelligence Observatory（信号情报观察站）**
- [x] `SignalIntelligenceService` 维护每个信号维度的 Information Coefficient (IC) 滚动序列（近5/20/60日），并推断 `alpha_halflife_days`（alpha 半衰期）。
- [x] `GET /api/v1/observability/signal-intelligence` 返回六维 IC 曲线、半衰期、拥挤度评分（Crowding Score）。
- [x] 信号拥挤度超阈值（`SIGNAL_CROWDING_WARN=0.75`）时，写入感知栏告警并降低该维度融合权重。

**P2 — Risk Observability Cluster（风险可观测集群）**
- [x] 实时计算五个主因子敞口（Market / HML / SMB / MOM / QMJ）并写入 `portfolio_factor_exposure` 快照，频率 5分钟/次。
- [x] `GET /api/v1/observability/risk-cluster` 返回因子敞口条、实时期望损失（ES@97.5%）、组合内相关性均值。
- [x] 组合内相关性均值骤升超 `CORRELATION_SPIKE_THRESHOLD=0.65` 时触发 `CORRELATION_SPIKE` 告警事件。

#### 二、AI 中枢 2.0 (AI Hub 2.0)

**P0 — Multi-Agent Orchestration（五智能体协作框架）**
- [x] `MultiAgentOrchestrator` 协调五个专职 Agent：`MarketAnalystAgent` / `RiskChallengerAgent` / `ExecutionOptimizerAgent` / `ResearchAgent` / `OrchestratorAgent`，每次决策周期通过结构化消息传递完成任务分工与冲突裁决。
- [x] Agent 间通信通过 `AgentMessage(agent_id, role, content, confidence, timestamp)` Pydantic schema 传递，全量写入 `agent_communication_log` 表以供溯源。
- [x] `RiskChallengerAgent` 必须对每个 BUY 信号输出反驳理由（`challenge_points: list[str]`），Orchestrator 最终综合裁决。

**P1 — AI Confidence Calibration（置信度校准系统）**
- [x] `ConfidenceCalibrationService` 每日 08:15 运行：将过去 90 日 `[confidence_bucket → actual_win_rate]` 映射写入 `confidence_calibration_snapshot` 表，计算 Brier Score 和 ECE（Expected Calibration Error）。
- [x] 当整体 ECE > `ECE_WARN_THRESHOLD=0.12` 时，在 AI 决策输出上自动叠加 `calibration_adjustment_factor`（向 0.5 方向收敛），并将校准状态写入感知栏。
- [x] `GET /api/v1/ai-hub/calibration` 返回分体制 Reliability Diagram 数据点、Brier Score 趋势、当前校准因子。

**P2 — Adaptive Factor Framework（自适应因子框架）**
- [x] `AdaptiveFactorWeightingService` 使用 Kalman Filter 对六维信号权重进行在线更新（观测值 = 最近5日 IC，过程噪声 Q=0.001，观测噪声 R=0.01），更新频率：每日收盘后。
- [x] 因子动量加成：近20日 IC 排名前两位的因子权重额外 +5%，排名末位因子权重 -5%，总权重归一化至100%。
- [x] 权重历史写入 `signal_weight_history`；`GET /api/v1/ai-hub/factor-weights` 返回当前权重与历史曲线。

**P3 — Decision Post-Mortem Engine（决策事后剖析引擎）**
- [x] `DecisionPostMortemService`：每笔持仓完全平仓后（`position_status=CLOSED`），自动触发 `deepseek-reasoner` 生成结构化复盘，包含：`factual_summary / counterfactual_buy / counterfactual_hold / counterfactual_sell / key_lessons / improvement_suggestions`。
- [x] 事后剖析结果写入 `decision_post_mortems` 表，并自动提炼1条 LESSON 型洞察推入 `ai_insight_repository`（`source=POST_MORTEM`）。
- [x] `GET /api/v1/ai-hub/post-mortems/{trade_id}` 返回完整剖析报告；`GET /api/v1/ai-hub/post-mortems` 支持分页浏览。

#### 三、指挥室演进 (War Room Dashboard)

**P0 — War Room Mode（全屏六格指挥视图）**
- [x] 新增 `/war-room` 路由，全屏 6 面板网格布局可由用户自由配置（拖拽 + 尺寸调整），面板类型含：P&L Ticker / Intelligence Feed / Portfolio Heatmap / Risk Gauges / Signal Pulse / Execution Queue Monitor。
- [x] 顶部实时 P&L Ticker：每5秒推送 `{ total_pnl, pnl_change_1h, top_contributor, top_detractor, vs_spy_alpha }`，支持归因下钻。
- [x] 全局键盘快捷键：`W` 进入 War Room / `Esc` 退出 / ` `` ` 全局 Copilot / 数字键 1-6 聚焦对应面板。

**P1 — Intelligence Feed（AI情报流）**
- [x] `IntelligenceFeedService` 聚合以下事件流并按 `urgency_score` 排序：Agent 决策摘要 / 告警事件 / 事件日历倒计时 / 因子异常 / Copilot 主动推送。
- [x] `GET /api/v1/war-room/intelligence-feed?limit=50` 返回带 urgency_score（0-100）、category（DECISION/RISK/EVENT/SIGNAL）、action_required 标记的事件列表。
- [x] WebSocket 推送：`ws://…/ws/intelligence-feed`，实时追加新事件，前端滚动展示。

**P2 — Portfolio Exposure Center（组合敞口中枢）**
- [x] `GET /api/v1/war-room/exposure` 返回：行业敞口分布（sector → net_exposure_pct）+ 五因子当前偏差（factor → z_score）+ 地理敞口（US/HK/Global）+ 持仓间相关矩阵。
- [x] 行业热力图：每格显示板块净敞口%、当日 P&L、对 SPY 的 Beta，Color scale：红（空头）→ 绿（多头）。

**P3 — Smart Alert Center（智能告警分级中枢）**
- [x] `SmartAlertService` 对原始告警进行 AI 分级（CRITICAL/HIGH/MEDIUM/LOW）+ 相似告警聚合（cosine similarity > 0.85 自动合并）+ 自动生成建议行动（`recommended_action_text`）。
- [x] Dashboard 告警中枢面板：按优先级排序列表 + 已读/忽略/采纳行动三种处理状态，采纳行动时触发 Copilot confirm 流程。
- [x] `GET /api/v1/war-room/alerts` 支持按 `severity / category / status` 筛选；`PATCH /api/v1/war-room/alerts/{alert_id}` 更新处理状态。

---

### V10.3.2 验收标准（归档）

- [x] 同一 `account_id + signal_id + symbol + action` 重复触发时，仅首个 execution intent 入库成功，后续被幂等拒绝。
- [x] 自主执行链路包含 execution intent 状态流转：`PENDING → EXECUTING → SUCCESS/FAILED`，以及 `SKIPPED/REJECTED` 分支。
- [x] 风控拒绝可观测：RiskGate/CircuitBreaker 拒绝分支同样写入 `autonomous_execution_intent(status=REJECTED)`。
- [x] 信号数量语义统一：`quantity_mode=PCT_EQUITY/ABS_SHARES` + `quantity_value`，并兼容历史 `suggested_quantity`。
- [x] `HOLD/qty<=0` 不再标记为 `EXECUTED`，改为 `SKIPPED`。
- [x] Dashboard 信号管道增加 `skipped_count`。

---

## 1. 产品愿景

打造**全自主量化交易 AI**：系统 7×24 自主运行完整交易闭环，人工只需设定边界（风险预算、标的池、自主度等级），AI 处理其余一切——从市场研究到下单执行，从自我复盘到策略进化。

### 1.1 核心理念

**Autonomous Alpha Loop（自主阿尔法闭环）**：

```
┌─────────────────────────────────────────────────────┐
│              AI 自主决策引擎（全天候运行）              │
│                                                       │
│  市场扫描 → 信号生成 → 组合决策 → 风险审查 → 自动执行  │
│      ↑                                        ↓      │
│  策略进化 ← 参数优化 ← 绩效归因 ← 结果分析 ← 持仓监控  │
│                                                       │
│  [人工层] 设定边界 / 审计日志 / 随时干预 / Copilot 查询│
└─────────────────────────────────────────────────────┘
```

**三层自主度模式**（全局配置 `AI_AUTONOMY_LEVEL`）：

| 模式 | 值 | AI 行为 | 人工角色 |
|------|----|---------|---------|
| **全自主** | `FULL` | AI 自主完成完整闭环，无需任何人工确认 | 设定边界 + 审计 |
| **半自主** | `SEMI` | AI 生成决策并执行，重大操作（单笔 > N%）推送通知 | 重大操作可在30分钟内撤销 |
| **建议模式** | `ADVISORY` | AI 生成所有建议，所有执行需人工确认 | 审核并点击确认 |

> **默认模式**：`SEMI`（半自主）——兼顾效率与安全，推荐个人实盘使用。

### 1.2 标的类型限制

**默认仅支持股票（STOCK）**，通过配置 `ALLOWED_ASSET_TYPES` 扩展：

```
ALLOWED_ASSET_TYPES=STOCK              # 默认：仅股票
ALLOWED_ASSET_TYPES=STOCK,ETF          # 扩展：股票+ETF
ALLOWED_ASSET_TYPES=STOCK,ETF,OPTION   # 开启期权（需谨慎）
```

- 策略库中涉及期权的策略（尾部对冲、铁鹰、波动率套利）在 `STOCK` 模式下自动跳过
- 期权分析中心作为**只读信息工具**，不受此限制（仍可看 IV、P/C Ratio 等指标辅助判断）

### 1.3 北极星指标

| 指标 | V9 目标 | V10 目标 |
|------|---------|---------|
| 交易闭环覆盖 | 100% | 100%（全自主） |
| 人工日常操作步数 | ≤ 5 步 | **0 步**（FULL 模式）/ ≤ 3 步（SEMI） |
| 信号到执行延迟 | < 3s（通知） | **< 5s**（直接执行） |
| AI 自主决策收益率 | N/A | ≥ SPY 年化收益 |
| Paper→Live 策略升级率 | N/A | ≥ 70%（回测胜率 ≥ 55% 才升级） |
| 系统可用性 | ≥ 99.5% | ≥ 99.5% |

---

## 2. 用户画像

### 2.1 目标用户

- **被动量化投资者**：希望 AI 全权管理，自己只审计结果
- **主动量化研究者**：配置策略池和参数，观察 AI 自主运行效果
- **人机协作交易者**：保留 ADVISORY 模式，借助 AI 提升决策质量

### 2.2 核心痛点（V10 升级应对）

| 痛点 | V9 应对 | V10 应对 |
|------|---------|---------|
| 信息过载，难以决策 | AI 给建议 | **AI 直接决策+执行**，人只看结果 |
| 执行拖延 | 推送通知让用户确认 | **零人工摩擦**（FULL 模式自动执行） |
| 复盘困难 | 手动填写日志 | **AI 自动生成**完整交易复盘+周报 |
| 风险失控 | 风险评分提示 | **AI 主动管理风险**（止损/对冲/减仓）|
| 情绪交易 | 行为评分提醒 | **消除人类情绪**（AI 无情绪，严格守纪）|

---

## 3. 系统功能架构

### 3.1 AI 自主交易闭环（V10.2 升级：17 阶段）

```
0⃣ Regime Classification（体制分类）★ V10.2-M1 新增
    ↓ 五维评分 → 6类体制识别 → 3日确认 → EventBus 广播 REGIME_CHANGED
① Market Scan（市场扫描）
    ↓ DataHub 多源行情 + 宏观风险实时评估
② Research（研究分析）
    ↓ 12大类策略并行扫描 + AI 多维评分
③ Signal Generation（信号生成）
    ↓ 信号引擎聚合，AI 决定候选标的
③.₅ Signal Fusion（信号融合）★ V10.2-M4 新增
    ↓ 多源信号聚合 + 体制权重加成 + Shapley 归因
④ Portfolio Decision（组合决策）
    ↓ Markowitz/风险平价/Kelly 最优仓位计算
④.₅ Regime-Aware Position Sizing（体制感知仓位）★ V10.2-M2 新增
    ↓ 按当前体制动态调整策略权重与仓位上限
⑤ Risk Gate（风险门禁）
    ↓ 体制自适应 VaR 门限 + CVaR 检查 + 压力测试
⑥ Execution（智能执行）
    ↓ 小单直接下单 / 大单 TWAP/VWAP 拆分
⑦ Monitoring（持续监控）
    ↓ 实时跟踪 + 止损/止盈自动触发
⑦.₅ Event-Driven Override（事件驱动干预）★ V10.2-M3 新增
    ↓ 重大事件（FOMC/财报）自动触发仓位保护
⑧ Evaluation（绩效评估）
    ↓ 每日 PnL 归因 + Alpha/Beta + 体制归因分解
⑧.₅ TCA Analysis（交易成本分析）★ V10.2-M6 新增
    ↓ 滑点/冲击成本/执行质量量化
⑨ Backtest Validation（回测验证）
    ↓ 策略参数变更前先跑 Walk-Forward 回测
⑨.₅ AI Self-Evolution（AI 自我进化）★ V10.2-M5 新增
    ↓ 策略权重参数在线学习 + 因子效力衰减监测
⑩ Adaptive Optimization（自适应优化）
    ↓ AI 自动调整策略权重 + 参数
⑪ Loop（自主循环）
    → 回到 0⃣ 持续进化，无需人工介入
```

**人工在哪里？**
- 初始化：设定风险预算、标的池、自主度等级
- 运行中：通过 Copilot 随时查询，重大操作（SEMI 模式）收通知可撤销
- 复盘：查看 AI 自动生成的周报，调整边界配置

### 3.2 核心模块

#### A. 数据与研究层
- **DataHub 多数据源聚合**：Tiger（实时，覆盖美股/港股/期权）→ yfinance（美股降级）→ Redis 缓存，优先级路由；港股及期权行情与美股股票使用同一套 Tiger API 优先策略，无需独立数据源
- **市场热点分析**：识别热门赛道和个股
- **宏观风险评分**：地缘政治 + 经济指标综合判断
- **技术面分析**：多指标技术分析（AI 自主触发）
- **基本面分析**：估值 + 成长性评估
- **事件日历** ★ V10.2-M2：yfinance 盈利日历 + 硬编码 FOMC/CPI/NFP，每日 07:00 同步，风险分级（LOW/MEDIUM/HIGH/CRITICAL）

#### B. AI 决策层（V10 核心升级）
- **策略库**：12大类量化策略（股票模式下跳过期权策略）
- **组合智能**：Markowitz + 风险平价 + Kelly，从单标的决策升级为组合视角
- **AI 自主决策引擎**：deepseek-reasoner / gpt-5.2 驱动，自主完成建议→决策全流程
- **风险门禁**：VaR/CVaR + 压力测试，双重把关，AI 不绕过
- **信号融合引擎** ★ V10.2-M4：六维加权融合（tech 25% / fundamental 20% / macro 15% / vol 15% / options 15% / sentiment 10%）+ 体制倍数加权
- **盈利围栏** ★ V10.2-M2：盈利前 1 天自动激活 50% 仓位上限，防止盈利期决策扭曲

#### C. 执行层
- **智能执行路由**：小单市价 → 大单 TWAP/VWAP 自动选择
- **Paper/Live 双轨**：新策略先走 Paper，回测通过后升级 Live
- **止损/止盈引擎**：AI 动态更新止损位（追踪止损）
- **动态仓位生命周期** ★ V10.2-M3：PositionStateMachine 三引擎（ScaleInEngine：盈利回调触发加仓；ScaleOutEngine：超目标分批减仓；TrailingStopEngine：14日 ATR 移动止损）

#### D. 监控与复盘层
- **价格告警**：条件触发，AI 自动评估是否需要干预
- **AI 自动复盘**：交易日志自动填写，AI 生成质量评估
- **AI 周报**：每周日自动推送 Telegram，全面覆盖收益/策略/行为三个维度
- **行为评分**：对 AI 自身决策质量打分（替代人类行为评分）
- **交易归因引擎** ★ V10.2-M5：三层向下钻取——Alpha 源贡献（策略/信号）/ 执行质量（滑点/时机）/ 仓位管理（加减仓/止损效果）
- **AI 进化引擎** ★ V10.2-M6：InsightService 自动抽取洞察（每周日 deepseek-reasoner）、ABTestEngine 策略 A/B 实验（scipy t-test 显著性检验，p<0.05 自动结论）
- **Copilot Partner** ★ V10.2-M7：DeepResearchEngine 多步深度研究报告（市场情绪→基本面→风险因素→综合评级）、ProactiveIntelligenceService 主动推送重大事件摘要

#### E. 可观测性 2.0 层 ★ V10.3.3 新增
- **Execution Microscope（执行显微镜）**：Implementation Shortfall 四分解（迟延成本/市场冲击成本/机会成本/时机成本），执行 Alpha 衡量（到达价 vs 实际成交价），按时段/标的热力图可视化
- **Signal Intelligence Observatory（信号情报观察站）**：IC 滚动序列（近5/20/60日），Alpha 半衰期估算，六维因子相关矩阵，信号拥挤度评分（Crowding Score > 0.75 自动降权）
- **Risk Observability Cluster（风险可观测集群）**：五因子实时敞口（Market/HML/SMB/MOM/QMJ），期望损失 ES@97.5% 实时仪表，组合内相关性骤升检测

#### F. AI 中枢 2.0 层 ★ V10.3.3 新增
- **Multi-Agent Orchestration（五智能体协作）**：MarketAnalystAgent / RiskChallengerAgent / ExecutionOptimizerAgent / ResearchAgent / OrchestratorAgent，结构化 `AgentMessage` 传递，全量通信日志溯源
- **AI Confidence Calibration（置信度校准）**：置信区间 → 实际胜率映射校准曲线，Brier Score + ECE 量化校准误差，自适应降评因子（ECE > 0.12 时自动介入）
- **Adaptive Factor Framework（自适应因子框架）**：Kalman Filter 在线权重更新，因子动量加成（近20日 IC 前两名 +5%），因子拥挤度检测
- **Decision Post-Mortem Engine（事后剖析）**：每笔平仓后自动生成反事实分析（BUY/HOLD/SELL 三条路径对比），洞察自动反哺 InsightService（source=POST_MORTEM）

## 4. 核心功能详述

### 4.1 AI 自主决策引擎（Autonomous Decision Engine）

**V10 核心升级**：不再是"AI 给建议 → 人决策"，而是"AI 直接决策并执行，人设定边界"。

**决策流程**：
```
1. 触发条件满足（定时 or 事件驱动，如价格突破/宏观事件）
2. AI 并行运行：技术面 + 基本面 + 宏观 + 策略信号 四维评分
3. 组合优化：计算最优仓位分配（Kelly/Markowitz）
4. 风险门禁：VaR 检查 + 压力测试（不通过则拒绝执行）
5. 决策记录：写入审计日志，推送 Telegram 通知（SEMI 模式）
6. 执行：小单市价 / 大单 TWAP/VWAP，独立的 Paper 或 Live 账户
```

**AI 决策输出**（完整 JSON）：
```json
{
  "decision_id": "uuid",
  "symbol": "AAPL",
  "asset_type": "STOCK",
  "direction": "LONG",
  "confidence": 78,
  "action": "BUY",
  "entry_price": 178.50,
  "stop_loss": 175.00,
  "take_profit": 186.00,
  "position_pct": 0.12,
  "kelly_fraction": 0.18,
  "portfolio_adjusted_pct": 0.12,
  "risk_level": "MEDIUM",
  "var_impact": -0.008,
  "execution_algo": "TWAP",
  "account_type": "PAPER",
  "autonomy_action": "AUTO_EXECUTE",
  "reasoning": "技术面强势(82分)，基本面健康(75分)，宏观低风险(68分)，Kelly建议18%但组合优化后压缩至12%",
  "scenarios": { "bull": { "prob": 0.45, "target": 186 }, "bear": { "prob": 0.25, "target": 172 } },
  "model_used": "deepseek-reasoner",
  "created_at": "2026-02-24T09:30:00Z"
}
```

**自主度控制**：
```
FULL  → autonomy_action = AUTO_EXECUTE（直接执行）
SEMI  → autonomy_action = AUTO_EXECUTE（执行后推送可撤销通知，30分钟内可撤）
ADVISORY → autonomy_action = PENDING_CONFIRM（等待人工确认）
```

**AI 模型路由**：
```
轻量决策辅助（技术指标计算、信号评分）→ deepseek-chat / gpt-4o-mini
核心交易决策（多维综合分析、组合优化）→ deepseek-reasoner / gpt-5.2
```

**决策安全边界**（AI 不可突破）：
- 单标的仓位 ≤ `MAX_SINGLE_POSITION_PCT`（默认 25%）
- 总风险敞口（VaR@95%）≤ `MAX_VAR_PCT`（默认 3%）
- 单日最大交易笔数 ≤ `MAX_DAILY_TRADES`（默认 10）
- 压力测试最大损失 ≤ `MAX_STRESS_LOSS_PCT`（默认 15%）
- 标的类型 ∈ `ALLOWED_ASSET_TYPES`（默认 STOCK）

### 4.2 交易计划（AI 自动生成 + 可选人工审核）

**V10 变化**：计划不再需要人工创建，AI 自主生成并根据自主度等级决定是否自动执行。

**生命周期**：
```
AI_GENERATED → [SEMI/FULL: AUTO_EXECUTING] / [ADVISORY: PENDING_CONFIRM]
                         ↓
              EXECUTED / CANCELLED / EXPIRED / FAILED
```

**来源字段** `source`：
- `AI_AUTONOMOUS`：AI 自主决策生成（V10 主流）
- `AI_ADVISORY`：AI 建议，人工确认（ADVISORY 模式）
- `MANUAL`：用户手动创建

**撤销机制**（SEMI 模式专用）：
- AI 执行后推送 Telegram："已执行 AAPL 买入 $178.50 × 100股 [撤销链接]"
- 30分钟内点击撤销链接，系统自动平仓（同价区间内市价反向）
- 超时则确认，写入日志

### 4.3 策略库（股票模式 = 10 类策略，期权模式 = 12 类）

**股票模式下启用（`ALLOWED_ASSET_TYPES=STOCK`）**：

#### A. 均值回归策略
1. **布林带均值回归** - 价格偏离均线 > 2σ
2. **配对交易** - 协整股票对价差（纯股票对）

#### B. 趋势跟踪策略
3. **突破动量** - 突破关键阻力/支撑位
4. **黄金交叉** - 短期均线上穿长期均线

#### C. 多因子策略
5. **Fama-French 三因子** - 市场/规模/价值因子
6. **动量+质量** - ROE + 价格动量综合

#### D. 防御策略
7. **低波动率** - 选择历史波动率最低的股票标的
8. **~~尾部对冲~~** ⛔ _仅 OPTION 模式可用_

#### E. 波动率策略（**仅参考，不执行**）
9. **~~铁鹰期权~~** ⛔ _仅 OPTION 模式可用_
10. **~~波动率套利~~** ⛔ _仅 OPTION 模式可用_

#### F. 宏观对冲策略
11. **行业轮动** - 经济周期驱动的板块切换（用股票 ETF 实现）
12. **CTA 商品** - 商品 ETF 趋势跟踪

**AI 自主策略调度**：
- 每日盘前 08:30 自动运行全部启用策略
- 宏观风险高（≥ 70分）时，自动提升防御策略权重
- 策略参数由 AdaptiveOptimizer 每日回测验证后自动更新

### 4.4 组合决策（Portfolio-Level AI Decision）

**V10 新增核心功能**：AI 不再逐个信号独立决策，而是**在组合层面统一决策**。

**流程**：
```
当日信号池（N个候选标的）
    ↓
AI 评分矩阵（技术 × 基本面 × 宏观 × 策略权重）
    ↓
协方差矩阵计算（过去252日日线收益率）
    ↓
Markowitz 最优化（最大化夏普，约束条件：VaR、仓位上限）
    ↓
Kelly 仓位修正（以 Half-Kelly 保守压缩）
    ↓
输出：最终执行标的列表 + 各标的仓位比例
```

**约束条件**（AI 强制遵守）：
- 总仓位 ≤ 95%（保留5%现金缓冲）
- 单行业集中度 ≤ 40%
- 与基准（SPY）相关性 ≤ 0.9（防止纯 Beta 持仓）

### 4.5 风险门禁（Risk Gate—AI 自我约束）

**定位**：AI 决策完成后、执行前的最后一道程序化护栏，不可配置关闭。

**检查链（串行，任一失败则拒绝）**：
```
① VaR@95% 检查：执行后组合 VaR ≤ MAX_VAR_PCT
② 压力测试快速版：COVID_2020 情景下损失 ≤ MAX_STRESS_LOSS_PCT
③ 仓位合规检查：单标的、行业集中度不超限
④ 标的类型检查：符合 ALLOWED_ASSET_TYPES
⑤ 频率检查：今日交易笔数未超 MAX_DAILY_TRADES
```

**拒绝后 AI 处理**：降低仓位比例后重新检查，若仍不过则放弃本次信号并记录原因。

### 4.6 回测验证（Backtest Validation—策略升级前置条件）

**Paper→Live 升级流程**：
```
新策略/参数变更
    ↓
自动触发 Walk-Forward 回测（最近2年日线，70/30 训练/测试集）
    ↓
评估：Sharpe ≥ 1.0 AND 最大回撤 ≤ 20% AND 胜率 ≥ 50%？
    ↓ 通过            ↓ 失败
Paper 账户运行30天  → 保留旧参数，记录失败原因
    ↓ Paper 胜率 ≥ 55%
升级 Live 账户（逐步放量：首月25% → 次月50% → 第三月100%）
```

**回测指标**：年化收益、最大回撤、Sharpe、Sortino、Calmar、胜率、盈亏比、Alpha vs SPY

### 4.7 Trading Copilot（人机协同接口）

**定位**：人工唯一主动交互入口，替代散落的按钮操作。用自然语言查询、下指令、或紧急干预。

**能力**：
- **查询**："今天 AI 做了哪些交易？""NVDA 当前持仓的盈亏是多少？"
- **分析**："当前组合的最大风险来自哪里？"（触发 deepseek-reasoner 深度分析）
- **指令**（需二次确认）："暂停所有自动交易""把 AAPL 止损改到175""清仓 TSLA"
- **配置**："把自主度切换到 ADVISORY 模式""把 NVDA 加入禁止交易名单"
- **主动推送**：盘前摘要（AI 今日计划）、异常事件提醒、盘后日报、周报

**AI 分层**：
```
查询类（单轮，上下文少）  → deepseek-chat / gpt-4o-mini（速度优先）
分析类（多轮，需推理）    → deepseek-reasoner / gpt-5.2（质量优先）
指令类                    → 固定逻辑处理，不走 LLM（安全优先）
```

### 4.8 TWAP/VWAP 执行算法

**AI 自动选择**（无需人工干预）：

| 条件 | 选择算法 |
|------|---------|
| 订单金额 < 账户净值 1% | 市价单（立即执行） |
| 订单金额 1%~5% | VWAP（30分钟） |
| 订单金额 > 5% | TWAP（60分钟，6份拆分） |
| 宏观风险 ≥ HIGH | 紧急模式：忽略大小，强制市价 |

### 4.9 AI 自动复盘与周报

**日报**（每日收盘后自动生成）：
- 今日 AI 决策汇总（执行了什么 / 为什么 / 结果如何）
- 策略贡献热力图
- 风险指标变化

**周报**（每周日 21:00 自动生成 + 推送 Telegram）：
```
📊 AI Alpha 周报 (2026-WXX)

📈 收益概览：本周 +2.3% vs SPY -0.5%（Alpha +2.8%）
🤖 AI 决策质量：置信度均值 73 / 胜率 62% / 平均 R:R 1:2.4
🎯 策略贡献：布林带 +1.1% / 低波动率 +0.8% / 突破动量 -0.3%
⚡ 执行质量：TWAP 滑点 0.06%（目标 < 0.1%）
🛡 风险回顾：最大日内 VaR 2.1%（上限 3%），安全
🔄 自适应更新：突破动量止损参数从 2.0% → 2.5%（回测改善 Sharpe +0.2）
💡 下周展望：宏观风险偏高，防御权重 +10%
```

---

## 4.X V10.2-M2~M7 新增功能详述

### 4.X.1 事件日历 & 盈利围栏（M2）

**目标**：在盈利/FOMC/CPI 等高影响力事件前，AI 自动收紧仓位管理，防止意外冲击。

**盈利围栏机制**：
- 盈利公布前 `PREEARNING_DAYS`（默认 1）天激活围栏
- 围栏激活 → 新建仓位和加仓操作自动上限 50%（`EARNINGS_FENCE_CAP=0.5`）
- 围栏可人工覆盖（需填写理由）
- 盈利结果录入后：自动解除围栏 + 记录 EPS 实际值与价格反应

**事件类型**：
| 事件类型 | 数据来源 | 风险等级 |
|---------|---------|---------|
| 单股盈利（EARNINGS）| yfinance.Ticker.calendar | HIGH/CRITICAL |
| FOMC 会议 | 硬编码 2025 年全年 | CRITICAL |
| CPI 数据 | 硬编码 2025 年全年 | HIGH |
| NFP 就业报告 | 硬编码 2025 年全年 | HIGH |

---

### 4.X.2 动态仓位生命周期（M3）

**目标**：用规则驱动的状态机取代静态止盈止损，实现持仓全生命周期精细化管理。

**PositionStateMachine 状态**：`INITIAL → PARTIAL → FULL → REDUCING → CLOSED`

**三类引擎触发条件**：

| 引擎 | 触发条件 | 操作 |
|------|---------|------|
| ScaleInEngine（加仓）| 价格从高点回调 > 30% × ATR，且原方向信号仍有效 | 加仓 25-50% |
| ScaleOutEngine（减仓）| 价格超过止盈目标 1.5× | 减仓 30-50% |
| TrailingStopEngine（移动止损）| 盈利超 1×ATR 后启用移动止损（Price - N×ATR，N=14日）| 动态更新止损位 |

---

### 4.X.3 六维信号融合（M4）

**目标**：取代单一技术信号，聚合六大数据维度形成高置信度融合信号，直接驱动 AI 决策。

**六维权重体系**（基础权重，体制可调整）：

| 维度 | 基础权重 | BULL_TREND 倍数 | CRISIS 倍数 |
|------|---------|---------------|------------|
| 技术面（Tech）| 25% | ×1.3 | ×0.8 |
| 基本面（Fundamental）| 20% | ×1.0 | ×0.9 |
| 宏观（Macro）| 15% | ×0.9 | ×1.5 |
| 波动率（Volatility）| 15% | ×0.9 | ×1.3 |
| 期权（Options）| 15% | ×1.1 | ×1.2 |
| 情绪（Sentiment）| 10% | ×1.0 | ×0.7 |

`composite_score = Σ(dim_score × effective_weight)`，归一化到 0-100。

---

### 4.X.4 三层交易归因（M5）

**目标**：让每笔已平仓交易的盈亏来源清晰可追溯，驱动 AI 策略自我进化。

**三层模型**：

```
总 PnL
├── Layer 1 — Alpha 源归因
│   识别哪个信号维度/策略带来超额收益
│   alpha_pnl = total_pnl × alpha_contribution_ratio
│
├── Layer 2 — 执行质量归因
│   量化滑点/时机差异对结果的影响
│   exec_pnl = (actual_fill - theoretical_price) × qty
│   exec_quality_score = 100 × (1 - |slippage_bps| / 50)
│
└── Layer 3 — 仓位管理归因
    量化加减仓决策和移动止损的贡献
    pos_mgmt_pnl = scale_in_gain + trailing_stop_savings
```

---

### 4.X.5 AI 自我进化引擎（M6）

**目标**：AI 像有记忆的专业交易员一样，从历史交易中提炼规律并持续改进。

**两大组件**：

1. **InsightService（周报洞察）**
   - 每周日 22:00 ET 由 `deepseek-reasoner` 自动运行
   - 分析过去 7 天 trade_attribution_entries
   - 生成 4 类洞察：WEEKLY_SUMMARY / PATTERN / LESSON / RULE_CANDIDATE
   - 洞察写入 `ai_insight_repository`，可人工激活/停用

2. **ABTestEngine（A/B 实验）**
   - 支持创建任意参数维度的对照实验（止损倍率/信号阈值等）
   - 每日 08:30 运行 `scipy.stats.ttest_ind` 双样本 t-test
   - p < 0.05 → 自动标记显著 + 生成结论
   - EvolutionPage 可视化所有实验状态与结果

---

### 4.X.6 Copilot Partner（M7）

**目标**：将 Copilot 从"被动 QA 助手"升级为"主动研究合伙人"。

**两大升级**：

1. **DeepResearchEngine（深度研究）**
   - `POST /api/v1/copilot/deep-research` 触发
   - 对任意标的执行 4步多轮推理：
     1. 市场情绪与近期走势分析
     2. 基本面价值评估（PE/增长/护城河）
     3. 风险因素清单（监管/竞争/宏观）
     4. 综合评级 + 价格目标区间
   - 返回结构化报告：`{rating, price_target, body, sources[]}`

2. **ProactiveIntelligenceService（主动推送）**
   - 订阅 EventBus 所有 Topic
   - 当 REGIME_CHANGED / EVENT_CALENDAR_UPDATED / CIRCUIT_BREAKER_TRIGGERED 等重大事件发生时
   - 自动通过 Copilot 推送摘要，无需用户主动询问

---

## 4.Y V10.3 新增功能详述——交易全链路可观测性（Full Trade Observability）

> **设计哲学（华尔街顶级量化标准）**  
> Citadel / Two Sigma 等机构核心教训：**AI 自主交易系统最大的风险不是决策错误，而是决策不透明**。当系统处于 FULL 自主模式时，人工唯一能做的是"观察并在边界处干预"——这要求系统以接近彭博终端级别的信息密度与实时性，将交易全链路的每一个状态节点暴露给审计者。V10.3 核心命题：**让 AI 的每一个动作都在玻璃墙后面运行**。

---

### 4.Y.1 核心设计原则

| 原则 | 具体体现 | 量化目标 |
|------|---------|---------|
| **全链路状态透明** | 每笔交易从信号诞生到平仓的每一步均有时间戳与状态标记 | 信息缺口率 = 0（无黑洞阶段）|
| **双维度生命周期** | 计划生命周期（Plan FSM）+ 持仓状态机（Position FSM）正交展示 | 任何交易可在 2 秒内定位当前所处阶段 |
| **17 阶段流水线可视化** | 实时 Kanban 泳道，每笔任务在流水线上的位置实时更新 | 流水线延迟异常检测 P95 < 10s |
| **AI 决策因果链溯源** | 从原始多维信号 → 融合评分 → 风险门禁 → 执行算法，每步决策依据可查 | 任意交易 → 完整 provenance 链路 < 3 次点击 |
| **异常驱动告警** | 状态机异常转换（如 FULL→CLOSED 跳跃 ScaleOut）自动标红 | 异常捕获率 100%，误报率 < 5% |
| **横向比较视图** | 多标的并排在同一时间轴上展示生命周期进展 | 同屏展示 ≤ 20 笔活跃交易 |

---

### 4.Y.2 Trade Lifecycle Center（交易生命周期中枢）

**定位**：系统新增一级核心页面（`/trade-lifecycle`），专门承载双维度生命周期可视化，是 V10.3 的旗舰功能。不替代现有 Journal/Positions 页，而是提供**动态过程视角**（Journal 记录结果，Lifecycle Center 展示过程）。

#### A. 顶部 — 17 阶段流水线泳道（Pipeline Kanban）

将 AI 自主闭环的 17 个阶段映射为横向泳道，每笔活跃交易任务（Task）在泳道中流动：

```
Stage 0   Stage 1    Stage 2    Stage③     Stage③.₅   Stage④      Stage④.₅   Stage⑤
体制分类  市场扫描   研究分析   信号生成   信号融合   组合决策   体制仓位    风险门禁
────────   ────────   ────────   ────────   ────────   ────────   ────────   ────────
           [NVDA]                [AAPL]                            [TSLA]
           [META]                                                  
                                 [MSFT]

Stage⑥    Stage⑦    Stage⑦.₅    Stage⑧    Stage⑧.₅   Stage⑨     Stage⑨.₅   Stage⑩    Stage⑪
智能执行  持续监控  事件干预    绩效评估   TCA分析   回测验证   AI进化    自适应优化  自主循环
────────   ────────  ────────   ────────   ────────   ────────   ────────   ────────   ────────
[AAPL]     [00700]              [NVDA]
           [AMZN]
```

**视觉规范**：
- 每个 Stage 列宽相等，任务卡片水平滚动
- 任务卡片颜色：
  - 🟢 正常流转（当前阶段时长在 P50 以内）
  - 🟡 轻度延迟（P50～P90）
  - 🔴 严重延迟（超 P90，触发告警）
  - ⚫ 已停滞（> 2× P95，需人工介入）
- 卡片悬停展示：当前阶段耗时、预计下阶段时间、置信度分数
- 点击任务卡片 → 跳转至底部 Decision Provenance 面板

**阶段聚合指标**（每列底部）：
- 当前滞留任务数
- 平均阶段耗时（与历史 P50 对比）
- 今日通过率（进入 → 通过 / 进入 → 总量）

---

#### B. 中部 — 双维度生命周期状态图（Dual FSM Panel）

左右分屏，同时展示两个维度的状态机：

**左侧 — 计划生命周期（Plan FSM）**：

```
                ┌──────────────────────────────────────────┐
                │ 计划生命周期（Plan Lifecycle）              │
                ├──────────────────────────────────────────┤
                │                                           │
  [AI_GENERATED] ──▶ [AUTO_EXECUTING] ──▶ [EXECUTED] ──▶ (归因) 
        │                  │                   │
        │ (ADVISORY)       │ 30min内            │
        ▼                  ▼                   │
  [PENDING_CONFIRM] ──▶ [REVOKED]            [FAILED]
        │
        ▼                              [CANCELLED]  [EXPIRED]
  [AUTO_EXECUTING]
                │
                ├──────────────────────────────────────────┤
                │ 活跃计划数: 3  今日已完成: 12  撤销: 1   │
                │ FULL:2  SEMI:1  ADVISORY:0               │
                └──────────────────────────────────────────┘
```

- 状态节点圆圈：包含当前处于该状态的计划数量（实时）
- 状态转换箭头：鼠标悬停显示触发条件
- 点击任意状态节点 → 底部列表过滤至该状态的计划

**右侧 — 持仓状态机（Position FSM）**：

```
                ┌──────────────────────────────────────────┐
                │ 持仓状态机（Position State Machine）       │
                ├──────────────────────────────────────────┤
                │                                           │
  [INITIAL] ──▶ [PARTIAL] ──▶ [FULL] ──▶ [REDUCING] ──▶ [CLOSED]
      │               ▲          │              │               
      │    ScaleIn     │  ScaleIn │  ScaleOut    │  TrailingStop
      │               │          ▼              ▼
      │               └──── [持仓加仓中]    [持仓减仓中]
      │                    (+25~50%)        (-30~50%)
      │
      │ (直接止损/风险门禁触发强制平仓)
      └────────────────────────────────▶ [CLOSED]
                │
                ├──────────────────────────────────────────┤
                │ INITIAL:1  PARTIAL:3  FULL:5             │
                │ REDUCING:2  CLOSED (今日):8               │
                │ 引擎触发次数: ScaleIn×3 ScaleOut×2 TS×1  │
                └──────────────────────────────────────────┘
```

**状态转换事件日志**（FSM 面板底部，滚动）：
```
10:32:15  AAPL   PARTIAL → FULL      ScaleInEngine 触发，入场价 $183.2，加仓 40%
10:18:04  NVDA   FULL    → REDUCING  ScaleOutEngine 触发，超止盈1.5×目标
09:45:22  META   INITIAL → PARTIAL   首次建仓，Plan #2840 执行完成
09:31:00  TSLA   REDUCING→ CLOSED   TrailingStop 触发，ATR×14=5.3%，锁利 +8.2%
```

---

#### C. 底部 — AI 决策溯源面板（Decision Provenance Drawer）

点击任意交易任务卡片展开，展示一笔交易的**完整因果链**：

```
┌─ AAPL BUY $183.20 × 120股 ─────────────────────────────────────────┐
│ 决策 #2847 | 置信度 78 | 状态: EXECUTING | 创建 10:14:32             │
├───────────────────────────────────────────────────────────────────┤
│ 📡 原始信号来源（SignalFusionEngine 输入）                           │
│ ┌────────────┬────────┬──────────┬────────────────────────────┐  │
│ │ 维度        │ 原始分  │ 体制权重  │ 最终贡献                    │  │
│ ├────────────┼────────┼──────────┼────────────────────────────┤  │
│ │ 技术面      │ 82     │ ×1.3     │ 26.7 / 32.5               │  │
│ │ 基本面      │ 75     │ ×1.0     │ 15.0 / 20.0               │  │
│ │ 宏观        │ 68     │ ×0.9     │ 9.2  / 13.5               │  │
│ │ 波动率      │ 71     │ ×0.9     │ 9.6  / 13.5               │  │
│ │ 期权        │ 65     │ ×1.1     │ 10.7 / 16.5               │  │
│ │ 情绪        │ 70     │ ×1.0     │ 7.0  / 10.0               │  │
│ ├────────────┴────────┴──────────┴────────────────────────────┤  │
│ │ 综合评分: 78.2  当前体制: BULL_TREND（置信度 85%）              │  │
│ └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│ ⚖️ 风险门禁检查链（全部通过 ✅）                                    │
│  ✅ VaR@95%: 执行后 2.4%  ≤ 3.0% 上限                            │
│  ✅ 压力测试: COVID_2020 场景损失 8.3%  ≤ 15% 上限               │
│  ✅ 仓位合规: 单标的 12%  ≤ 25% 上限                              │
│  ✅ 标的类型: STOCK ∈ ALLOWED_ASSET_TYPES                        │
│  ✅ 频率: 今日 3 笔  ≤ 10 笔上限                                  │
│                                                                    │
│ 🤖 AI 决策摘要（from reasoning 字段）                              │
│  "技术面强势(82分)，BULL_TREND 体制下技术权重上调至1.3×；基本面     │
│   健康(75分)，Q4 EPS 超预期12%；组合优化后从 Kelly 建议18%压缩至    │
│   12%，TWAP 30分钟执行（订单约占净值 2.1%）"                       │
│                                                                    │
│ ⚡ 执行详情（ExecutionAlgo）                                       │
│  算法: TWAP  时长: 30min  拆单: 6份 × 20股                        │
│  已成交: 4/6份  均价: $183.18  目标均价: $183.20  滑点: -0.01%   │
│                                                                    │
│ [查看完整 JSON] [跳转归因分析] [跳转持仓] [撤销交易]               │
└───────────────────────────────────────────────────────────────────┘
```

---

### 4.Y.3 智能订单簿（Intelligent Order Book）

**定位**：新增页面 `/order-book`，统一替代分散在 AI Advisor + Journal + Positions 中的交易列表视图。提供**实时更新的全量交易视图**，包含今日活跃 + 近 7 天历史。

#### 主列表设计（每行信息密度对标 Bloomberg Terminal Order Sheet）：

| 字段 | 内容 | 样式 |
|------|------|------|
| **标的** | 代码 + 中英文名 + 市场标签（US/HK）+ 资产类型图标 | 主字段，可点击跳转 |
| **方向** | LONG ↑ / SHORT ↓ | 绿/红色方向箭头 |
| **触发阶段** | 信号诞生于哪个模块（策略名称缩写） | 策略徽章（色码） |
| **当前阶段** | 17 阶段中的具体阶段编号 + 名称 | 进度徽章 |
| **入场目标价** | AI 建议入场区间（low ～ high） | 价格组 |
| **实际成交均价** | 已成交时显示，偏差用颜色标记 | 实际 vs 目标对比 |
| **止损价** | 当前动态止损位（TrailingStop 实时更新）| 红色价位 |
| **止盈目标** | 原始 + 动态止盈位（ScaleOut 调整后）| 绿色价位 |
| **仓位 %** | 当前占净值比例（含 ScaleIn 后变动）| mini 进度条 |
| **浮盈 / PnL** | 实时浮盈金额 + 百分比 | 正绿负红 |
| **置信度** | 原始 AI 评分（0-100）+ 六维雷达迷你图 | 评分徽章 |
| **风险标记** | 盈利围栏 🔒 / 体制预警 ⚡ / 流动性警告 💧 | 图标徽章 |
| **AI 摘要** | reasoning 字段前 80 字，悬停展开全文 | Truncated text |
| **操作** | [详情] [撤销] [修改止损] | 操作按钮组 |

#### 列表视图布局：

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 📋 智能订单簿                    [活跃: 7] [今日已完成: 12] [待确认: 2]   [筛选▼] [导出] │
├────────────────────────────────────────────────────────────────────────────────────┤
│ 分组：▸ 活跃执行中 (3)            ▸ 持仓监控中 (4)            ▸ 今日已完成 (12)      │
│──────────────────────────────────────────────────────────────────────────────────── │
│ 🟢 活跃执行中                                                                        │
│ 标的        方向  策略源       当前阶段          入场目标     成交均价  止损    PnL    │
│ 🇺🇸AAPL    ↑BUY  [布林带]  ⑥执行·TWAP 4/6  $183.0~183.5  $183.18  $178.0  执行中  │
│ 概述: "技术强势(82)，BULL_TREND加权，Q4 EPS超预期，Kelly 18%→组合压至 12%"           │
│ ─────────────────────────────────────────────────────────────────────────────────  │
│ 🇺🇸NVDA    ↑BUY  [突破动量] ⑥执行·VWAP 1/3  $890.0~895.0  $891.30  $870.0  执行中  │
│ 概述: "突破关键阻力 $888，成交量放大 2.3×，情绪面超预期，配对 ETF 流入强劲"           │
│──────────────────────────────────────────────────────────────────────────────────── │
│ 🔵 持仓监控中                                                                        │
│ 标的        方向  策略源       当前阶段          成本价      现价      止损    浮盈    │
│ 🇺🇸MSFT    ↑LONG [Fama-FF]  ⑦监控·PARTIAL    $415.20   $428.50  $405.0  +$1,330  │
│ 🔒盈利围栏  [ScaleIn 可用]  "多因子强信号，ROE 40%+，PEG 1.8 合理估值区间"           │
│ ─────────────────────────────────────────────────────────────────────────────────  │
│ 🇭🇰00700   ↑LONG [行业轮动] ⑦监控·FULL       HK$356.0   HK$371.0  HK$348  +HK$3,000│
│ ⚡BEAR_TREND预警  "腾讯，港股互联网轮动信号，政策环境改善，体制权重已下调至0.8×"     │
└──────────────────────────────────────────────────────────────────────────────────── ┘
```

#### 辅助功能：

- **高级筛选**：按方向 / 资产类型 / 市场 / 阶段范围 / 策略来源 / 风险标记 / 账户类型（Paper/Live）
- **置信度六维迷你雷达图**：悬停在置信度数字上，展示六维蛛网图
- **价格偏差列**：成交均价与 AI 入场目标价对比（超差 > 0.3% 自动标黄）
- **批量操作**：全选活跃订单，批量 [修改止损] / [标记观察]

---

### 4.Y.4 系统态势感知栏（System Situational Awareness Bar）

**定位**：全局顶部粘性状态栏（高度 36px），在所有页面持续展示系统关键状态，取代需要点击进入专页才能看到的碎片化状态信息。灵感来源：Bloomberg Terminal 状态栏 + Citadel 内部 Risk Dashboard 常驻水位条。

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 🌊体制: BULL_TREND⬆85%  │ ⚠️VaR: 2.4%/3.0%[████████░░]  │ 📅围栏: MSFT🔒(明日财报)  │
│ ⑥执行中: AAPL·NVDA     │ 🕐等待确认: 2笔(ADVISORY)      │ 🤖FULL自主 ● 运行中      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**信息分区（从左到右优先级递减）**：

| 区块 | 内容 | 更新频率 | 颜色逻辑 |
|------|------|---------|---------|
| **体制状态** | 当前体制名称 + 置信度 + 趋势箭头 | 每日（体制确认后）| 体制类型色码 |
| **VaR 水位** | 当前 VaR% / 上限% + mini 进度条 | 每 5 分钟 | 绿/黄/红 |
| **事件围栏** | 今日/明日激活的盈利围栏标的 | 实时 | 橙色警告 |
| **活跃执行** | 正在执行的交易标的（TWAP/VWAP 进行中）| 实时 | 蓝色动画点 |
| **待确认** | ADVISORY 模式下等待人工确认的计划数 | 实时 | 若>0 则黄色闪烁 |
| **自主模式** | FULL/SEMI/ADVISORY + 运行/暂停状态 | 实时 | 绿色(运行)/红色(暂停) |

**点击任意区块** → 导航至对应详情页。
**ADVISORY 待确认 > 0** → 区块红色闪烁 + 点击直接展示确认面板。

---

### 4.Y.5 后端 API 新增需求

#### 交易生命周期查询接口

```
GET  /api/v1/lifecycle/pipeline              — 17 阶段流水线当前状态（所有活跃任务分布）
GET  /api/v1/lifecycle/plan-fsm              — 计划生命周期 FSM 状态统计（各状态计划数）
GET  /api/v1/lifecycle/position-fsm          — 持仓 FSM 状态统计（各状态持仓数 + 当日引擎触发次数）
GET  /api/v1/lifecycle/fsm-events            — FSM 状态转换事件流（最近 N 条，支持 offset）
GET  /api/v1/lifecycle/provenance/{plan_id}  — 单笔交易决策溯源完整链路
```

#### 订单簿接口

```
GET  /api/v1/order-book                      — 全量订单视图（活跃+今日历史，支持分页+筛选）
GET  /api/v1/order-book/summary              — 聚合摘要（活跃数/已完成/待确认/今日 PnL）
GET  /api/v1/order-book/{plan_id}/detail     — 单笔订单完整详情（含执行进度+仓位状态）
PATCH /api/v1/order-book/{plan_id}/stop-loss — 修改活跃持仓止损位（Copilot 指令下发）
```

#### 态势感知接口

```
GET  /api/v1/situational-awareness           — 全局状态聚合（体制/VaR/围栏/执行队列/自主模式）
WS   /ws/v1/situational-awareness            — WebSocket 推送（任意状态变更时实时推送）
```

---

### 4.Y.6 数据模型扩展

在现有 `trade_plan` 表新增字段：

```sql
-- 生命周期溯源字段
pipeline_stage      SMALLINT        -- 当前所处 17 阶段编号（0-17）
stage_entered_at    TIMESTAMPTZ     -- 进入当前阶段的时间戳
stage_history       JSONB           -- 各阶段进入/退出时间戳数组
provenance_snapshot JSONB           -- 决策溯源快照（六维分数 + 风险门禁结果）
position_fsm_state  VARCHAR(20)     -- 关联的 Position FSM 当前状态
```

在现有 `positions` / `position_states` 表新增：

```sql
fsm_transition_log  JSONB           -- 状态机转换事件日志（时间戳 + 触发引擎 + 操作详情）
engine_trigger_count JSONB          -- 各引擎触发计数 {scale_in: N, scale_out: N, trailing: N}
```

---

### 4.Y.7 北极星指标（V10.3）

| 指标 | 定义 | V10.3 目标 |
|------|------|-----------|
| 生命周期透明度 | 活跃交易中可完整追溯 provenance 链路的比例 | 100% |
| 状态延迟可见性 | 流水线异常（超 P90 阶段耗时）到告警展示的延迟 | < 10s |
| 决策可解释性 | 每笔执行交易可在 3 次点击内查到完整六维信号来源 | 100% |
| 订单簿实时性 | 执行状态更新到界面反映的延迟 | < 3s（WebSocket）|
| 态势感知准确性 | 系统实际状态与 Awareness Bar 展示一致率 | ≥ 99.9% |

---

## 5. 技术要求

### 5.1 性能指标

| 指标 | 要求 |
|------|------|
| AI 决策完成（含组合优化）| P95 < 8s |
| 信号到执行延迟 | < 5s（FULL 模式） |
| API 响应时间（非 AI） | P95 < 500ms |
| 回测任务（1年日线，1策略）| < 30s |
| Dashboard 刷新 | ≤ 30s |
| 系统可用性 | ≥ 99.5% |

### 5.2 AI 安全要求

- **决策可解释性**：每笔 AI 交易必须写入 `reasoning` 字段，可追溯
- **强制审计日志**：所有 AI 执行操作写入不可删除的 `audit_log` 表
- **熔断机制**：单日亏损 ≥ `MAX_DAILY_LOSS_PCT`（默认 3%）时自动暂停 AI 自动交易
- **人工覆盖权**：任何时刻调用 `/api/v1/autonomy/pause` 可立即暂停所有自动执行
- **标的白名单**：`ALLOWED_SYMBOLS` 配置项（空=全部允许）

### 5.3 配置边界（全局安全参数）

```bash
# AI 自主度
AI_AUTONOMY_LEVEL=SEMI           # FULL / SEMI / ADVISORY

# 标的类型限制
ALLOWED_ASSET_TYPES=STOCK        # STOCK / STOCK,ETF / STOCK,ETF,OPTION

# 风险边界（AI 不可突破）
MAX_SINGLE_POSITION_PCT=0.25     # 单标的最大仓位
MAX_VAR_PCT=0.03                 # 组合最大 VaR@95%
MAX_STRESS_LOSS_PCT=0.15         # 压力测试最大容忍损失
MAX_DAILY_TRADES=10              # 单日最大交易笔数
MAX_DAILY_LOSS_PCT=0.03          # 单日亏损熔断线

# Paper Trading
PAPER_INITIAL_CAPITAL=100000     # Paper 账户初始资金
PAPER_AUTO_GRADUATE=true         # 是否自动升级符合条件的策略到 Live

# 数据源（美股/港股/期权统一使用 Tiger API 优先）
DATA_HUB_PRIMARY=tiger           # tiger / yfinance
DATA_HUB_FALLBACK=yfinance        # Tiger 不可用时降级 yfinance（主要覆盖美股）
# 港股/期权行情：Tiger API 为唯一正式来源，不引入 Futu API

# AI 模型
AI_LIGHTWEIGHT_MODEL=deepseek-chat    # 轻量决策
AI_COMPLEX_MODEL=deepseek-reasoner    # 复杂分析
```

### 5.4 安全与合规

- JWT 认证 + bcrypt 密码加密
- API Rate Limit（100 req/min）
- 敏感操作 + AI 决策 双重审计日志
- 熔断记录、撤销记录完整保存 ≥ 180 天

---

## 6. 成功标准

### 6.1 功能完整性

- ✅ 11 阶段 AI 自主闭环全覆盖
- ✅ AI 自主决策引擎（FULL/SEMI/ADVISORY 三模式）
- ✅ 回测验证 + Paper→Live 升级路径
- ✅ 投资组合级别决策（Markowitz + Kelly）
- ✅ 风险门禁（VaR + 压力测试不可绕过）
- ✅ TWAP/VWAP 智能执行路由
- ✅ AI 自动周报 + 日报
- ✅ Trading Copilot 人机接口

### 6.2 用户体验

- FULL 模式：**人工日常操作 = 0 步**（纯审计）
- SEMI 模式：核心干预 ≤ 3 步（看通知 → 决定是否撤销）
- 配置修改（自主度 / 风险边界 / 标的池）通过 Copilot 自然语言完成
- Dashboard 实时展示 AI 运行状态

### 6.3 业务指标

- AI 自主决策年化收益率 ≥ SPY（α > 0）
- Paper 策略验证通过率 ≥ 70%（胜率≥55%）
- AI 决策平均置信度 ≥ 65
- TWAP/VWAP 执行滑点 < 0.1%/单
- 熔断触发率 < 5%/月

---

## 7. 路线图

### Phase 1–5: 已完成 ✅
- 核心闭环、AI 决策、实时化、策略库、自适应优化

### Phase 6: 研究基础设施 🚀 V10 当前
- **回测引擎**：事件驱动，Walk-Forward，支持10类股票策略
- **DataHub**：Tiger → Polygon → yfinance 优先级路由
- **Paper Trading 账户隔离**：独立 account_id，模拟/实盘双轨

### Phase 7: AI 自主闭环核心 🚀 V10 核心
- **AI_AUTONOMY_LEVEL 三模式**（FULL / SEMI / ADVISORY）
- **组合级决策**（Markowitz + Kelly + 风险门禁）
- **压力测试**（5个历史情景 + 自定义）
- **Paper→Live 自动升级机制**（回测通过 + PA验证）
- **熔断机制 + 操作撤销**（SEMI 模式30分钟窗口）

### Phase 8: AI 深度升级 🚀 V10 当前
- **Trading Copilot**：对话式人机接口，替代散落的按钮
- **AI 自动周报/日报**：Telegram + 系统内存档
- **决策可解释性**：每笔交易 `reasoning` 字段 + 审计日志
- **AI 模型路由**：deepseek-chat/gpt-4o-mini（轻量）+ deepseek-reasoner/gpt-5.2（复杂）

### Phase 9: 执行精细化 🚀 V10 当前
- **TWAP/VWAP 自动路由**（AI 按订单大小自动选择）
- **期权分析中心**（只读信息工具，不执行）：IV曲面、P/C Ratio、异常成交

### Phase 10: 标的扩展 🚀 V10.1 当前
- **ETF 正式支持**（`STOCK,ETF` 模式）：行业轮动 + CTA 商品策略真正运行
- **港股 & 期权行情统一走 Tiger API**：港股（HK 市场）及期权行情数据优先通过老虎证券 API 获取，与美股股票保持一致的 DataHub 路由策略（Tiger → yfinance fallback），不引入 Futu API
- **Tiger 真实下单（美股 + 港股 + 期权）**：TigerOrderExecutor 完整实现，支持 US / HK 双市场及期权下单，FULL 模式实盘可用
- **FULL 模式完整自主闭环**：无需人工干预，AI 自主完成决策→下单→审计
- **Copilot 执行落地**：止损修改 / TWAP 下单 / 清仓三类指令实际执行
- **Dashboard 真实化**：VaR、宏观风险、执行指标、策略统计全部消除占位符
- **AI 组合级决策**：批量信号统一组合视角决策 + JSON 结构化输出消除 regex
- **Paper→Live 毕业自动化**：定时任务检测 + 自动升级
- **Dashboard WebSocket**：实时增量推送，降低延迟至 5s

### Phase 11: 全链路可观测性 ✅ V10.3 完成
- **Trade Lifecycle Center**：17阶段 PipelineKanban + DualFSM 双状态机可视化
- **Intelligent Order Book**：高密度全量订单列表，统一替代 AI Advisor + Journal 孤岛视图
- **Decision Provenance Drawer**：信号 → 风控 → 执行完整因果链溯源
- **Situational Awareness Bar**：全局粘性态势感知栏（体制/VaR/围栏/队列/模式）
- **执行幂等主键**：`autonomous_execution_intent` + 状态机（V10.3.2）
- **信号数量语义统一**：`quantity_mode + quantity_value` 标准化（V10.3.2）

### Phase 12: AI可观测性 & 指挥室 → 稳定性治理 ✅ V10.3.3 ~ V10.3.4 已完成（归档）
- **Execution Microscope**：Implementation Shortfall 四分解（迟延/市场冲击/机会/时机成本）
- **Signal Intelligence Observatory**：Alpha Decay 信号半衰期 + 因子相关矩阵 + 拥挤度检测
- **Risk Observability Cluster**：五因子实时敞口 + ES@97.5% 仪表 + 相关性骤升告警
- **Multi-Agent Orchestration**：五专职 Agent 协作框架（市场/风险/执行/研究/总协调）
- **AI Confidence Calibration**：Reliability Diagram + Brier/ECE + 自适应降评
- **Adaptive Factor Framework**：Kalman Filter 在线权重更新 + 因子动量加成
- **Decision Post-Mortem Engine**：事后剖析（反事实分析）+ 自动洞察反哺
- **War Room Mode**：全屏六格指挥视图 + 实时 P&L Ticker + 键盘快捷键
- **Intelligence Feed**：AI情报流（urgency 排序 + WebSocket 实时追加）
- **Portfolio Exposure Center**：行业/因子/地理敞口 + 相关矩阵
- **Smart Alert Center**：AI分级 + 告警聚合 + 建议行动

### Phase 13: 巩固、治理与完整性 🚀 V10.4 当前规划
> 详细规划见：[docs/archived/v10/v10.4/RELEASE_PLAN_V10.4.md](archived/v10/v10.4/RELEASE_PLAN_V10.4.md)

- **M1 数据闭环治理**：`actual_return` 自动回填 Job + IC 真实化（移除 fallback）+ 因子快照自动化 + 2026 年事件日历 + LLM 调用 `LLMCallGuard`
- **M2 UI 大清洗**：47 页 → ≤38 页，6 导航组 → 4 组，执行三页合并，双仪表盘合并，系统监控整合
- **M3 Copilot 全局化**：全局浮窗（Cmd+K）+ 页面上下文注入 + 实时系统状态 System Prompt
- **M4 自主循环稳定增强**：AutonomyHealthMonitor 自检 + JobWatchdog + Multi-Agent 真实并发 + WebSocket 重连
- **M4.1 系统监控增强**：`/system` 补齐交易生命周期监测、主数据流链路监测、模块与细粒度服务状态树，形成统一运维视图
- **M5 移动触达**：Dashboard/Alert/Copilot 三场景 375px 竖屏可用
- **M6 文档重构**：PRODUCT.md 拆分为模块化多文件，主文件 ≤300 行

### Phase 14: V11 计划 🔜
- 期权执行开启（`STOCK,ETF,OPTION` 全模式）
- 多账户 / 多用户支持
- LLM Fine-tuning 个人交易风格适配
- 实时 L2 订单簿深度分析
- 移动端原生 App（iOS/Android）

---

## 8. V10 新功能 API 速览

### 8.1 自主度控制
```
GET  /api/v1/autonomy/status            — 查询当前自主度和运行状态
PUT  /api/v1/autonomy/level             — 修改自主度级别
POST /api/v1/autonomy/pause             — 立即暂停 AI 自动交易
POST /api/v1/autonomy/resume            — 恢复 AI 自动交易
GET  /api/v1/autonomy/audit-log         — 查询 AI 决策审计日志
POST /api/v1/autonomy/revoke/{exec_id}  — 撤销 AI 执行（SEMI 模式，30分钟内）
```

### 8.2 回测引擎
```
POST /api/v1/backtest/run               — 提交回测任务（异步）
GET  /api/v1/backtest/tasks             — 查询任务列表
GET  /api/v1/backtest/tasks/{id}        — 查询任务状态/进度
GET  /api/v1/backtest/tasks/{id}/report — 获取完整报告
GET  /api/v1/backtest/compare           — 多策略对比（最多5个）
DELETE /api/v1/backtest/tasks/{id}      — 删除任务
```

### 8.3 投资组合优化
```
POST /api/v1/portfolio/optimize          — 运行组合优化
GET  /api/v1/portfolio/efficient-frontier — 有效前沿散点
GET  /api/v1/portfolio/risk-contribution  — 各标的风险贡献
POST /api/v1/portfolio/rebalance-plan    — 生成再平衡计划
```

### 8.4 压力测试
```
POST /api/v1/stress-test/run             — 运行压力测试
GET  /api/v1/stress-test/scenarios       — 获取情景库
POST /api/v1/stress-test/custom          — 自定义情景
```

### 8.5 Trading Copilot
```
POST /api/v1/copilot/chat                — 发送消息
GET  /api/v1/copilot/history             — 获取会话历史
DELETE /api/v1/copilot/history           — 清空会话
POST /api/v1/copilot/confirm/{action_id} — 确认指令操作
GET  /api/v1/copilot/morning-brief       — 盘前摘要
GET  /api/v1/copilot/daily-report        — 当日复盘
```

### 8.6 执行算法
```
POST /api/v1/execution/algo/submit       — 提交 TWAP/VWAP 任务
GET  /api/v1/execution/algo/tasks        — 查询任务列表
GET  /api/v1/execution/algo/tasks/{id}   — 查询单任务状态
DELETE /api/v1/execution/algo/tasks/{id} — 取消任务
```

### 8.7 期权分析中心（只读）
```
GET  /api/v1/options/iv-surface/{symbol}     — IV 曲面数据
GET  /api/v1/options/iv-rank/{symbol}        — IV Rank/Percentile
GET  /api/v1/options/unusual-activity        — 异常成交扫描
GET  /api/v1/options/put-call-ratio/{symbol} — P/C Ratio
GET  /api/v1/options/chain/{symbol}          — 期权链报价（只读）
GET  /api/v1/options/expiry-calendar         — 到期日日历
```

### 8.8 Paper Trading
```
GET  /api/v1/paper/status                    — Paper 账户状态
POST /api/v1/paper/reset                     — 重置 Paper 账户
GET  /api/v1/paper/performance               — Paper 账户绩效
GET  /api/v1/paper/graduation-candidates     — 可升级 Live 的策略列表
POST /api/v1/paper/graduate/{strategy_id}    — 手动升级策略到 Live
```

### 8.9 市场体制感知（V10.2-M1）
```
GET  /api/v1/regime/current              — 查询当前体制及置信度
GET  /api/v1/regime/history              — 历史体制记录（分页）
GET  /api/v1/regime/strategy-weights     — 当前体制下各策略权重
POST /api/v1/regime/override             — 人工覆写当前体制（管理员）
```

### 8.10 可观测性 2.0（V10.3.3 新增）
```
# Execution Microscope — 执行质量
GET  /api/v1/observability/execution-quality           — 聚合执行质量：IS分解/Fill Rate/vs VWAP偏差
GET  /api/v1/observability/execution-quality/{intent_id} — 单笔 IS 四分解明细
GET  /api/v1/observability/fill-heatmap                — 按时段×标的的成交率热力图数据

# Signal Intelligence Observatory — 信号情报
GET  /api/v1/observability/signal-intelligence         — 六维信号 IC 曲线、半衰期、拥挤度评分
GET  /api/v1/observability/signal-correlation          — 六维信号相关矩阵（滚动60日）
GET  /api/v1/observability/crowding-alerts             — 当前触发拥挤告警的信号维度

# Risk Observability Cluster — 风险可观测
GET  /api/v1/observability/risk-cluster                — 五因子敞口 + ES@97.5% + 组合内相关性均值
GET  /api/v1/observability/factor-exposure             — 因子敞口历史快照（分页）
GET  /api/v1/observability/correlation-alerts          — 相关性骤升事件历史
```

### 8.11 AI 中枢 2.0（V10.3.3 新增）
```
# Multi-Agent Orchestration — 多智能体协作
GET  /api/v1/ai-hub/agent-runs                         — Agent 协作运行记录（分页）
GET  /api/v1/ai-hub/agent-runs/{run_id}                — 单次运行完整通信日志（AgentMessage 链）
GET  /api/v1/ai-hub/agent-runs/{run_id}/challenge      — RiskChallengerAgent 反驳摘要

# Confidence Calibration — 置信度校准
GET  /api/v1/ai-hub/calibration                        — Reliability Diagram 数据 + Brier Score + ECE + 当前校准因子
GET  /api/v1/ai-hub/calibration/history                — 校准指标历史趋势（按体制分组）

# Adaptive Factor Framework — 自适应因子框架
GET  /api/v1/ai-hub/factor-weights                     — 当前六维权重（含 Kalman 更新后的权重）
GET  /api/v1/ai-hub/factor-weights/history             — 权重演变历史曲线
GET  /api/v1/ai-hub/factor-momentum                    — 各因子近5/20/60日 IC 排名与动量加成状态

# Decision Post-Mortem — 决策事后剖析
GET  /api/v1/ai-hub/post-mortems                       — 所有已剖析交易列表（分页）
GET  /api/v1/ai-hub/post-mortems/{trade_id}            — 单笔完整剖析报告（含反事实分析）
GET  /api/v1/ai-hub/post-mortems/patterns              — 跨剖析归纳的重复模式摘要（AI 提炼）
```

### 8.12 指挥室（War Room）（V10.3.3 新增）
```
# Real-time P&L Ticker
GET  /api/v1/war-room/pnl-ticker                       — 实时 P&L 快照（total/1h变化/贡献最大/Alpha vs SPY）
WS   /ws/pnl-ticker                                    — WebSocket 实时 P&L 推送（5s/帧）

# Intelligence Feed — AI情报流
GET  /api/v1/war-room/intelligence-feed                — 按 urgency_score 排序的情报事件列表（limit/offset）
WS   /ws/intelligence-feed                             — WebSocket 实时追加新事件
POST /api/v1/war-room/intelligence-feed/{event_id}/ack — 标记情报已读

# Portfolio Exposure Center — 组合敞口
GET  /api/v1/war-room/exposure                         — 行业敞口 + 五因子 z-score + 地理敞口 + 相关矩阵

# Smart Alert Center — 智能告警
GET  /api/v1/war-room/alerts                           — 分级告警列表（severity/category/status 筛选）
PATCH /api/v1/war-room/alerts/{alert_id}               — 更新告警处理状态（READ/IGNORED/ACTION_TAKEN）
GET  /api/v1/war-room/alerts/stats                     — 告警统计（按等级/类别/处理状态）
```

### 8.13 系统监控增强（V10.4.3 追加需求）
```
# Lifecycle Monitor — 交易生命周期监控
GET  /api/v1/system-monitor/lifecycle                  — 17阶段分布、Plan/Position FSM、stuck intents、异常阶段摘要
GET  /api/v1/system-monitor/lifecycle/{intent_id}      — 单笔 intent 的阶段轨迹、最近异常、耗时明细

# Data Flow Monitor — 关键数据流链路监控
GET  /api/v1/system-monitor/data-flows                 — 主链路节点状态（heartbeat/lag/queue_depth/last_error）
GET  /api/v1/system-monitor/data-flows/{flow_name}     — 单条数据流详情与最近失败样本

# Service Topology Monitor — 模块与细粒度服务状态
GET  /api/v1/system-monitor/services                   — 模块树状态（DB/Redis/Tiger/LLM/Scheduler/WebSocket/Autonomy/Observability）
GET  /api/v1/system-monitor/services/{service_name}    — 单服务健康详情、24h 错误计数、降级与恢复时间线
```

---

## 附录

### A. 术语表

| 术语 | 定义 |
|------|------|
| Autonomous Alpha Loop | AI 自主完整交易闭环 |
| Risk Gate | 执行前强制风险检验，不可配置关闭 |
| Paper→Live Graduation | 策略经回测+模拟验证后升级实盘的流程 |
| Revoke Window | SEMI 模式下 AI 执行后30分钟内的人工撤销窗口 |
| Circuit Breaker | 单日亏损超阈值时自动暂停 AI 自动交易的熔断机制 |
| Walk-Forward | 滚动训练/测试的回测方法，防止参数过拟合 |
| Alpha | 组合超越 SPY 基准的超额收益 |
| Greeks | 期权风险指标（Delta/Gamma/Vega/Theta），在 STOCK 模式下仅做参考展示 |
| MarketRegime | 当前市场体制（BULL_TREND/BEAR_TREND/HIGH_VOL/MEAN_REVERT/RANGE_BOUND/CRISIS）|
| RegimeClassifier | 五维评分体制分类器，每日 08:00 自动运行，3日连续确认才切换 |
| EventBus | 异步发布/订阅事件总线，解耦体制感知与策略执行模块 |
| StrategyWeightAllocator | 订阅 REGIME_CHANGED 事件并更新 TaskConfig 策略权重的分配器 |
| VaR Multiplier | 体制感知 VaR 门限倍数（危机体制时收紧至 0.5×，牛市趋势时放宽至 1.2×）|
| EarningsFence | 盈利公布前自动激活的仓位上限围栏（默认 50%，可人工覆盖）|
| PositionStateMachine | 仓位全生命周期状态机（INITIAL→PARTIAL→FULL→REDUCING→CLOSED）|
| SignalFusionEngine | 六维加权信号融合引擎，输出 0-100 综合置信度评分 |
| TradeAttributionEngine | 三层 PnL 归因引擎（Alpha源 / 执行质量 / 仓位管理）|
| InsightService | 每周日 AI 自动从历史交易提炼洞察写入知识库的服务 |
| ABTestEngine | A/B 实验管理（scipy t-test 显著性检验，p<0.05 自动结论）|
| DeepResearchEngine | Copilot 多步深度研究引擎（4步推理 → 结构化报告）|
| ImplementationShortfall | 执行成本四分解：迟延成本（Delay Cost）+ 市场冲击成本（Market Impact）+ 机会成本（Opportunity Cost）+ 时机成本（Timing Cost）|
| AlphaDecay | 信号携带超额收益信息的衰减过程；Alpha 半衰期（Half-Life）越短，信号时效越紧迫 |
| InformationCoefficient (IC) | 信号预测值与实际收益的 Spearman 相关系数，衡量信号预测质量 |
| SignalCrowding | 当多数市场参与者持有相同方向信号时，拥挤度过高会降低 Alpha，系统通过 Crowding Score 预警 |
| FactorExposure | 组合对 Fama-French 五因子（Market/HML/SMB/MOM/QMJ）的净偏度，用 z-score 衡量 |
| ExpectedShortfall (ES) | ES@97.5%：最坏 2.5% 情景下的平均损失，比 VaR 更保守的尾部风险度量 |
| MultiAgentOrchestration | 多个专职 AI Agent 协作框架：MarketAnalystAgent / RiskChallengerAgent / ExecutionOptimizerAgent / ResearchAgent / OrchestratorAgent |
| RiskChallengerAgent | 专门扮演"反方"角色的 Agent，对每笔 BUY 信号生成结构化反驳理由，防止 AI 决策过度自信 |
| ConfidenceCalibration | 将 AI 置信度（0-100）校准至对应实际胜率的过程；Reliability Diagram / Brier Score / ECE 是核型校准评估工具 |
| BrierScore | 置信度预测准确性的综合评分（越低越好），= Σ(p_i - o_i)² / N |
| ECE (Expected Calibration Error) | 期望校准误差，量化预测置信度与实际频率的平均偏差，> 0.12 触发自适应降评 |
| KalmanFilter | 递归贝叶斯滤波器，用于实时估计动态系统状态（此处用于在线更新六维信号权重）|
| FactorMomentum | 近期表现强的因子持续表现强的效应，系统通过 IC 排名动态加成 |
| DecisionPostMortem | 每笔平仓交易后的结构化复盘，含反事实分析（三条路径对比）并自动生成 LESSON 型洞察 |
| WarRoomMode | Dashboard 全屏指挥视图，六格可配置布局，支持键盘驱动，面向高强度监控场景 |
| IntelligenceFeed | AI 情报流，聚合 Agent 决策摘要 / 告警 / 事件倒计时 / 因子异常，按 urgency_score 实时排序推送 |
| SmartAlertCenter | 智能告警分级中枢，AI 自动分级（CRITICAL/HIGH/MEDIUM/LOW）+ 相似告警聚合 + 建议行动生成 |

### B. 参考文档

- API.md - 接口文档（V10.3 已含所有端点）
- BACKEND_DESIGN.md - 后端架构设计（V10.3）
- FRONTEND_DESIGN.md - 前端 UI/UX 设计（V10.3.4）
- docs/RELEASE_NOTES_V10.3.md - V10.3 完整发布说明
