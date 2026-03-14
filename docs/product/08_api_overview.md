<!-- 源自 docs/PRODUCT.md §8. V10 新功能 API 速览 + 附录 -->

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

### 8.14 信号质量漏斗与幽灵交易（V10.4.2 新增）
```
GET  /api/v1/signals/quality-config               — 查看信号质量参数（含运行时覆盖值）
PATCH /api/v1/signals/quality-config              — 热更新质量参数（无需重启）
GET  /api/v1/signals/audit-log                    — 信号质量漏斗全量决策日志（分层结果 + conviction 评分）
GET  /api/v1/signals/funnel-stats                 — 漏斗各层统计（通过率 / 拒绝原因分布 / ELITE 占比）
GET  /api/v1/signals/ghost-trades                 — 幽灵交易列表（Layer 3/4 拒绝信号的虚拟跟踪）
GET  /api/v1/signals/ghost-trades/analysis        — 幽灵胜率 vs 实际胜率对比（量化"拒绝成本"）
```

### 8.15 Alpha Truth Stack（V10.5.1 M1）
```
GET  /api/v1/alpha-lab/strategies                 — 全策略 Scorecard 2.0（四层口径 + 分体制收益分解）
GET  /api/v1/alpha-lab/strategies/{id}/ic         — 单策略 IC 曲线（近5/20/60日，按 Regime/Capacity Bucket）
GET  /api/v1/alpha-lab/shadow-rejects             — Shadow False-Reject 列表（被漏斗误拒的潜在 alpha）
GET  /api/v1/alpha-lab/signal-decay               — Alpha 衰减曲线（半衰期趋势）
```

### 8.16 Portfolio Construction 2.0（V10.5.1 M2）
```
GET  /api/v1/portfolio/construction/risk-budget   — 各标的风险预算使用率与剩余容量
GET  /api/v1/portfolio/construction/marginal      — Alpha/Risk/Turnover/Liquidity 四维边际贡献矩阵
GET  /api/v1/portfolio/construction/liquidity     — 标的流动性评分与日均成交额匹配度
```

### 8.17 Execution Policy Engine（V10.5.1 M3）
```
GET  /api/v1/execution-policy/snapshot            — 当前生效的执行策略参数快照
GET  /api/v1/execution-policy/pre-trade-cost/{signal_id} — 单笔信号预估冲击成本
GET  /api/v1/execution-policy/child-orders        — 子订单执行进度列表（大单拆分）
GET  /api/v1/execution-policy/child-orders/{id}/replay — 单次执行路径重现与质量评估
```

### 8.18 Research-to-Live Governance（V10.5.1 M4）
```
GET  /api/v1/governance/pipeline                  — 策略晋级流水线状态（五阶段证据链）
GET  /api/v1/governance/pipeline/{strategy_id}    — 单策略完整证据链（含 promotion blockers / rollback reasons）
GET  /api/v1/governance/experiments               — Experiment Ledger（策略全生命周期实验历史）
POST /api/v1/governance/experiments/{id}/promote  — 手动触发策略晋级（需通过 blocker 检查）
```

### 8.19 Live Safety & Model Degradation（V10.5.1 M5）
```
GET  /api/v1/live-safety/status                   — 实盘安全状态（LLM 降级状态 / 数据源健康 / 决策延迟 P95）
GET  /api/v1/live-safety/degradation-events       — 模型降级事件历史（含触发条件与恢复时间）
POST /api/v1/live-safety/acknowledge/{event_id}   — 确认已处理降级告警
```

### 8.20 席位竞争仲裁（V10.5.2 新增）
```
GET  /api/v1/capacity/config                      — 查看当前容量仲裁参数（含运行时覆盖值）
PATCH /api/v1/capacity/config                     — 热更新仲裁参数（重启后恢复默认）
POST /api/v1/capacity/preview                     — Dry-run 仲裁预演（返回候选排序与淘汰清单，不实际执行）
GET  /api/v1/capacity/logs                        — 仲裁决策日志列表（支持 dry_run / 时间范围 / 触发来源过滤）
GET  /api/v1/capacity/logs/{log_id}               — 单条仲裁日志详情（含候选评分明细）
GET  /api/v1/capacity/stats                       — 仲裁指标摘要（触发次数、替换成功率、保护带命中率）
```

### 8.21 Capital Intelligence & Self-Perception（V11.0.1 已上线）

```text
GET  /api/v1/autonomy/meta-state                — 最新系统元状态快照（MetaState）
GET  /api/v1/autonomy/friction-state            — 当前摩擦积累信号列表
GET  /api/v1/autonomy/false-hold-alerts         — False-Hold 告警列表
GET  /api/v1/autonomy/improvement-candidates    — Improvement Lab 候选列表
```

**文档约束**：

- 以上端点均以 `app/routers/autonomy.py` 当前实现为准
- 不把未公开的 refresh / mutation 类接口写成已上线

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

- API.md - 接口文档（已对齐 V11.0.1 autonomy 端点）
- BACKEND_DESIGN.md - 后端架构设计（已对齐 V11.0.1）
- FRONTEND_DESIGN.md - 前端 UI/UX 设计（已对齐 V11.0.1 Autonomy 视图）
- docs/architecture/v11_0_1_implementation_design.md - V11.0.1 当前实现设计
- docs/archived/v11/v11.0/RELEASE_PLAN_V11.0.1.md - V11.0.1 历史规划归档
