<!-- 源自 docs/PRODUCT.md §文件顶部：版本历史、变更摘要、验收标准 -->

# 产品需求文档 (PRD)

> **AI量化交易闭环系统** - 个人美港股智能交易平台  
> 版本：V10.4.3（开发中）| 更新日期：2026-03-06  
> 变更摘要（V10.4.3）：**风险降低优先执行（Risk-Reducing Priority Execution）**——新增减仓/平仓快速通道：`REDUCE/EXIT` 信号绕过开仓型质量漏斗、熔断期间允许风险降低类订单、减仓/平仓不占用 `MAX_DAILY_TRADES` / `MAX_DAILY_SIGNALS` 配额；`PositionMonitor` 止损/止盈信号写入 `force_exit=true`，`AutonomousEngine` 识别后跳过冷却与 Redis 并发锁直接执行；`SignalPositionFilter` 在减仓数量超持仓时自动升级为全平；`OrderExecutor` 以实际持仓数量为准执行 EXIT/REDUCE，并为港股退出保留 odd-lot 平仓能力；`AutonomyPage` 新增“减仓/平仓优先通道”状态卡与快速通道/强制出场徽章。  
> 变更摘要（V10.4.1）：**巩固、治理与完整性**——M1 数据闭环治理（actual_return 自动回填 Job + IC 真实化 + 因子快照自动化 + 2026 事件日历 + LLM 降级）；M2 UI 大清洗（47→≤38 页面 + 导航 6→4 组 + 执行三合一 + 双仪表盘合并）；M3 Copilot 全局浮窗（Cmd+K 任意页面唤起 + 页面上下文注入 + 实时系统状态 System Prompt）；M4 自主循环稳定增强（AutonomyHealthMonitor + Job Watchdog + Multi-Agent 真实并发 + 三新熔断 + WebSocket 重连）；M5 移动触达（Dashboard/Alert/Copilot 竖屏可用）；M6 文档重构（PRODUCT.md 拆分为模块化多文件，主文件 ≤300 行）  
> 变更摘要（V10.3.4）：**稳定性与冷启动治理（Stability & Cold-Start Governance）**——全服务冷启动双保险（Dashboard / 代理运行状态 / 执行质量记录 / 置信度校准补全零数据占位逻辑，消除前端 404 抖动）；**市场全量股票池（Market Universe Pool）**——新增 `market_universe` 表，支持美股/港股全量标的同步与缓存；**AI 决策深化**——自主引擎支持 REDUCE/EXIT 信号规则执行，`HOLD/qty≤0` 语义纠偏为 SKIPPED（no-op 原因落库），信号管道新增 `quantity_mode/quantity_value` 标准化；**决策事后剖析升级**——从手工录入升级为交易选择驱动；**多账户兼容**——告警/归因/仪表板接口统一账户 ID 解析；**事件去重**——事件表唯一索引 + 重复写入保护  
> 变更摘要（V10.3.3）：**P0 可观测性 2.0（Observability 2.0）**——Execution Microscope 执行显微镜（IS 成本四分解：迟延成本/市场冲击/机会成本/时机成本）+ Signal Intelligence Observatory 信号情报观察站（Alpha Decay Monitor 信号半衰期曲线 + Factor Correlation Matrix + Crowding Detector）+ Risk Observability Cluster（实时因子敞口条 + Tail Risk ES 仪表 + 相关性骤升告警）；**P1 AI中枢 2.0（AI Hub 2.0）**——Multi-Agent Orchestration 五智能体协作框架（市场分析 / 风险挑战 / 执行优化 / 深度研究 / Orchestrator 总协调）+ AI Confidence Calibration 置信度校准系统（Reliability Diagram + 自适应降评）+ Adaptive Factor Framework 自适应因子框架（Kalman Filter实时权重更新 + 因子拥挤度检测）+ Decision Post-Mortem Engine 决策事后剖析（反事实分析 + 洞察反哺 InsightService）；**P2 指挥室演进（War Room Dashboard）**——War Room Mode 全屏六格指挥视图 + real-time P&L Ticker + Intelligence Feed AI情报流 + Portfolio Exposure Center 组合敞口中枢 + Smart Alert Center 智能告警分级中枢
> 变更摘要（V10.3.2）：**P0 执行幂等主键（Execution Intent）**——新增 `autonomous_execution_intent` 表与 `idempotency_key` 唯一约束，确保同一信号同一动作只受理一次；**P1 统一执行入口强化**——`AutonomousEngine.run_decision_cycle` 内统一进入 execution-intent 状态机（PENDING/EXECUTING/SUCCESS/FAILED/SKIPPED/REJECTED），并补齐 RiskGate/CircuitBreaker 拒绝分支的 intent 落库；**P2 语义一致性升级**——交易信号新增 `quantity_mode + quantity_value`（`PCT_EQUITY` / `ABS_SHARES`）并在自主决策链路标准化解析，且补齐策略引擎/快捷交易/交易计划/持仓监控等入口写入，`HOLD/qty<=0` 由 `EXECUTED` 语义纠偏为 `SKIPPED`。
> 变更摘要（V10.3）：**交易全链路可观测性（Full Trade Observability）**——Trade Lifecycle Center（交易生命周期中枢）双维度可视化（计划生命周期状态机 + 持仓生命周期状态机）+ 实时甘特泳道图；**智能订单簿（Intelligent Order Book）**——统一交易列表（标的/方向/价位/17阶段进度/AI简述/实时P&L/风险标记），替代分散的 AI Advisor + Journal 孤岛视图；**AI 决策溯源面板（Decision Provenance）**——从原始信号到最终执行的完整因果链可视化；**系统态势感知栏（System Situational Awareness Bar）**——全局粘性状态栏，实时聚合体制/VaR水位/事件围栏/活跃阶段/执行队列等关键状态  
> 变更摘要（V10.2-M2~M8）：**事件驱动风控**——EventCalendarService 盈利/FOMC/CPI/NFP 日历同步 + EarningsFenceService 盈利围栏（盈利前1天50%仓位上限）；**动态仓位生命周期**——PositionStateMachine 三引擎（ScaleIn/ScaleOut/TrailingStop）；**信号融合**——SignalFusionEngine 六维加权评分（tech 25%/fundamental 20%/macro 15%/vol 15%/opt 15%/sentiment 10%）+ 体制倍数；**交易归因**——TradeAttributionEngine 三层分析（Alpha源/执行质量/仓位管理）+ AttributionPage 可视化；**AI 进化**——InsightService 自动周报（deepseek-reasoner Sunday 22:00 ET）+ ABTestEngine（scipy t-test p<0.05）+ EvolutionPage；**Copilot Partner**——DeepResearchEngine 多步深度研究 + ProactiveIntelligenceService 主动推送  
> 变更摘要（V10.2-M1）：**市场体制感知引擎** ——RegimeClassifier 五维评分体系（趋势强度/波动率制度/量价关系/宏观环境/广度指标）、6类体制自动识别（BULL_TREND / BEAR_TREND / HIGH_VOL / MEAN_REVERT / RANGE_BOUND / CRISIS）、3日确认防噪机制、EventBus 异步事件总线（REGIME_CHANGED 事件驱动策略权重自适应切换、VaR 门限动态调整）、StrategyWeightAllocator 体制感知仓位分配、AI 自主交易闭环升级至 **17 阶段**  
> 变更摘要（V10.1）：**兑现承诺 + 打磨质量 + 扩展边界**——Tiger 真实下单接入（覆盖美股/港股/期权）、FULL 模式完整自主交易闭环、Copilot 操作指令执行落地、Dashboard 所有 TODO 指标真实化、AI 组合级决策升级（结构化 JSON 输出 + 批量组合决策）、ETF 标的池正式支持、港股支持（Tiger API 统一，无需 Futu）、Paper→Live 毕业自动化、Dashboard WebSocket 实时推送；**本版本明确不含 Telegram 通知，FULL 模式具备完全自主交易能力**

> 历史版本：V10.0（2026-02-24）变更摘要见下方历史记录节  
> 详细规划：[V10.4.1 Release Plan](../archived/v10/v10.4/RELEASE_PLAN_V10.4.md)

---

### V10.4.1 验收标准（已发布）

> 完整规划详见 [docs/archived/v10/v10.4/RELEASE_PLAN_V10.4.md](../archived/v10/v10.4/RELEASE_PLAN_V10.4.md)

#### M1 — 数据闭环治理

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
- [ ] `ExecutionMicroscopeService` 计算 Implementation Shortfall (IS) 四分解：`delay_cost + market_impact_cost + opportunity_cost + timing_cost`，每笔 intent 完成后写入 `execution_quality_log` 表。
- [ ] `GET /api/v1/observability/execution-quality` 返回按时段/标的聚合的 Fill Rate、IS 分解、vs VWAP deviation 三组指标。
- [ ] Dashboard 执行质量面板：Execution Alpha（到达价 vs 实际成交价）色码热力图，实时 P95 滑点数值。

**P1 — Signal Intelligence Observatory（信号情报观察站）**
- [ ] `SignalIntelligenceService` 维护每个信号维度的 Information Coefficient (IC) 滚动序列（近5/20/60日），并推断 `alpha_halflife_days`（alpha 半衰期）。
- [ ] `GET /api/v1/observability/signal-intelligence` 返回六维 IC 曲线、半衰期、拥挤度评分（Crowding Score）。
- [ ] 信号拥挤度超阈值（`SIGNAL_CROWDING_WARN=0.75`）时，写入感知栏告警并降低该维度融合权重。

**P2 — Risk Observability Cluster（风险可观测集群）**
- [ ] 实时计算五个主因子敞口（Market / HML / SMB / MOM / QMJ）并写入 `portfolio_factor_exposure` 快照，频率 5分钟/次。
- [ ] `GET /api/v1/observability/risk-cluster` 返回因子敞口条、实时期望损失（ES@97.5%）、组合内相关性均值。
- [ ] 组合内相关性均值骤升超 `CORRELATION_SPIKE_THRESHOLD=0.65` 时触发 `CORRELATION_SPIKE` 告警事件。

#### 二、AI 中枢 2.0 (AI Hub 2.0)

**P0 — Multi-Agent Orchestration（五智能体协作框架）**
- [ ] `MultiAgentOrchestrator` 协调五个专职 Agent：`MarketAnalystAgent` / `RiskChallengerAgent` / `ExecutionOptimizerAgent` / `ResearchAgent` / `OrchestratorAgent`，每次决策周期通过结构化消息传递完成任务分工与冲突裁决。
- [ ] Agent 间通信通过 `AgentMessage(agent_id, role, content, confidence, timestamp)` Pydantic schema 传递，全量写入 `agent_communication_log` 表以供溯源。
- [ ] `RiskChallengerAgent` 必须对每个 BUY 信号输出反驳理由（`challenge_points: list[str]`），Orchestrator 最终综合裁决。

**P1 — AI Confidence Calibration（置信度校准系统）**
- [ ] `ConfidenceCalibrationService` 每日 08:15 运行：将过去 90 日 `[confidence_bucket → actual_win_rate]` 映射写入 `confidence_calibration_snapshot` 表，计算 Brier Score 和 ECE（Expected Calibration Error）。
- [ ] 当整体 ECE > `ECE_WARN_THRESHOLD=0.12` 时，在 AI 决策输出上自动叠加 `calibration_adjustment_factor`（向 0.5 方向收敛），并将校准状态写入感知栏。
- [ ] `GET /api/v1/ai-hub/calibration` 返回分体制 Reliability Diagram 数据点、Brier Score 趋势、当前校准因子。

**P2 — Adaptive Factor Framework（自适应因子框架）**
- [ ] `AdaptiveFactorWeightingService` 使用 Kalman Filter 对六维信号权重进行在线更新（观测值 = 最近5日 IC，过程噪声 Q=0.001，观测噪声 R=0.01），更新频率：每日收盘后。
- [ ] 因子动量加成：近20日 IC 排名前两位的因子权重额外 +5%，排名末位因子权重 -5%，总权重归一化至100%。
- [ ] 权重历史写入 `signal_weight_history`；`GET /api/v1/ai-hub/factor-weights` 返回当前权重与历史曲线。

**P3 — Decision Post-Mortem Engine（决策事后剖析引擎）**
- [ ] `DecisionPostMortemService`：每笔持仓完全平仓后（`position_status=CLOSED`），自动触发 `deepseek-reasoner` 生成结构化复盘，包含：`factual_summary / counterfactual_buy / counterfactual_hold / counterfactual_sell / key_lessons / improvement_suggestions`。
- [ ] 事后剖析结果写入 `decision_post_mortems` 表，并自动提炼1条 LESSON 型洞察推入 `ai_insight_repository`（`source=POST_MORTEM`）。
- [ ] `GET /api/v1/ai-hub/post-mortems/{trade_id}` 返回完整剖析报告；`GET /api/v1/ai-hub/post-mortems` 支持分页浏览。

#### 三、指挥室演进 (War Room Dashboard)

**P0 — War Room Mode（全屏六格指挥视图）**
- [ ] 新增 `/war-room` 路由，全屏 6 面板网格布局可由用户自由配置（拖拽 + 尺寸调整），面板类型含：P&L Ticker / Intelligence Feed / Portfolio Heatmap / Risk Gauges / Signal Pulse / Execution Queue Monitor。
- [ ] 顶部实时 P&L Ticker：每5秒推送 `{ total_pnl, pnl_change_1h, top_contributor, top_detractor, vs_spy_alpha }`，支持归因下钻。
- [ ] 全局键盘快捷键：`W` 进入 War Room / `Esc` 退出 / ` `` ` 全局 Copilot / 数字键 1-6 聚焦对应面板。

**P1 — Intelligence Feed（AI情报流）**
- [ ] `IntelligenceFeedService` 聚合以下事件流并按 `urgency_score` 排序：Agent 决策摘要 / 告警事件 / 事件日历倒计时 / 因子异常 / Copilot 主动推送。
- [ ] `GET /api/v1/war-room/intelligence-feed?limit=50` 返回带 urgency_score（0-100）、category（DECISION/RISK/EVENT/SIGNAL）、action_required 标记的事件列表。
- [ ] WebSocket 推送：`ws://…/ws/intelligence-feed`，实时追加新事件，前端滚动展示。

**P2 — Portfolio Exposure Center（组合敞口中枢）**
- [ ] `GET /api/v1/war-room/exposure` 返回：行业敞口分布（sector → net_exposure_pct）+ 五因子当前偏差（factor → z_score）+ 地理敞口（US/HK/Global）+ 持仓间相关矩阵。
- [ ] 行业热力图：每格显示板块净敞口%、当日 P&L、对 SPY 的 Beta，Color scale：红（空头）→ 绿（多头）。

**P3 — Smart Alert Center（智能告警分级中枢）**
- [ ] `SmartAlertService` 对原始告警进行 AI 分级（CRITICAL/HIGH/MEDIUM/LOW）+ 相似告警聚合（cosine similarity > 0.85 自动合并）+ 自动生成建议行动（`recommended_action_text`）。
- [ ] Dashboard 告警中枢面板：按优先级排序列表 + 已读/忽略/采纳行动三种处理状态，采纳行动时触发 Copilot confirm 流程。
- [ ] `GET /api/v1/war-room/alerts` 支持按 `severity / category / status` 筛选；`PATCH /api/v1/war-room/alerts/{alert_id}` 更新处理状态。

---

### V10.3.2 验收标准（归档）

- [x] 同一 `account_id + signal_id + symbol + action` 重复触发时，仅首个 execution intent 入库成功，后续被幂等拒绝。
- [x] 自主执行链路包含 execution intent 状态流转：`PENDING → EXECUTING → SUCCESS/FAILED`，以及 `SKIPPED/REJECTED` 分支。
- [x] 风控拒绝可观测：RiskGate/CircuitBreaker 拒绝分支同样写入 `autonomous_execution_intent(status=REJECTED)`。
- [x] 信号数量语义统一：`quantity_mode=PCT_EQUITY/ABS_SHARES` + `quantity_value`，并兼容历史 `suggested_quantity`。
- [x] `HOLD/qty<=0` 不再标记为 `EXECUTED`，改为 `SKIPPED`。
- [x] Dashboard 信号管道增加 `skipped_count`。
