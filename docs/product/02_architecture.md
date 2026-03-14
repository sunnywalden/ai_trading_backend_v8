<!-- 源自 docs/PRODUCT.md §3. 系统功能架构 -->

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
- **CapacityArbiterService** ★ V10.5.2：统一候选池席位竞争，动态替换末位持仓（详见模块 H）

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

#### G. 信号质量治理层 ★ V10.4.2 新增

- **SignalQualityFunnel（五层漏斗）**：Layer 0（宇宙过滤：标的池黑白名单）→ Layer 1（体制门控：策略/体制兼容性）→ Layer 2（组合预检：MAX_CONCURRENT_POSITIONS / MAX_DAILY_SIGNALS 硬约束）→ Layer 3（多维共振：技术/基本面对立或 CRISIS 做多时 conviction=0）→ Layer 4（置信度校准门：SignalConvictionScorer 质量评级）
- **SignalConvictionScorer（信号质量评级）**：输出 LOW / MEDIUM / HIGH / ELITE 四级质量标签；conviction 公式：`composite×0.4 + resonance_bonus×0.25 + regime_alignment×0.15 + historical_ic×0.1 + timing_quality×0.1`；ELITE 信号豁免 `MAX_DAILY_SIGNALS` 限制（但不豁免仓位/RiskGate）
- **GhostTradeService（幽灵交易追踪）**：Layer 3/4 拒绝信号自动创建虚拟跟踪，每日价格更新，计算"幽灵胜率 vs 实际胜率"对比，量化误拒代价；数据表：`signal_quality_audit_logs / ghost_trades`

#### H. 席位竞争层 ★ V10.5.2 新增

- **CapacityArbiterService（席位仲裁服务）**：将当前持仓与新信号统一放入候选池，按 `admission_score = alpha_quality - replacement_friction - risk_penalty + regime_fit` 排序；满仓时淘汰末位 N 项（持仓 → `FORCE_EXIT`，信号 → `REJECTED_BY_CAPACITY_REPLACEMENT`）
- **PositionScoringService（持仓动态评估）**：实现 Incumbent Decay Model，持仓质量随时间衰减，定期重新参与席位竞争
- **替换保护机制**：`MIN_REPLACEMENT_EDGE_BPS`（最小替换优势）/ `MAX_REPLACEMENTS_PER_CYCLE`（每轮最多替换数）/ `MIN_HOLD_MINUTES_BEFORE_REPLACEMENT`（最短持有时间门槛）/ `REPLACEMENT_COOLDOWN_MINUTES`（冷却期），防止过度翻仓
- **审计与治理**：`capacity_decision_audit_log` 全量记录评分与淘汰原因；`CAPACITY_REPLACEMENT_DRY_RUN` 模式支持先观测后执行
- **Decision Post-Mortem Engine（事后剖析）**：每笔平仓后自动生成反事实分析（BUY/HOLD/SELL 三条路径对比），洞察自动反哺 InsightService（source=POST_MORTEM）

#### I. Capital Intelligence & Autonomous Evolution OS ★ V11.0.1 已上线

- **ConvictionFrictionTracker**：追踪 near-miss 开仓信号被阈值持续阻断的摩擦状态，支撑 soft-relief 判定
- **MetaStateSnapshotService**：生成系统自知画像，聚合 `throttled_signals`、`false_hold_alerts`、`capital_state`、`model_state`
- **ImprovementCandidateService**：基于元状态自动生成结构化改进候选，用于 Improvement Lab
- **CapitalVelocityService**：从资本效率视角解释“为什么资金闲置 / 为什么席位没有被更快轮转”
- **Feature Flags**：`CAPITAL_VELOCITY_V1101_ENABLED`、`SELF_PERCEPTION_V1101_ENABLED`、`IMPROVEMENT_ENGINE_V1101_ENABLED`、`EVOLUTION_GOVERNANCE_V1101_ENABLED`、`STYLE_ALIGNMENT_V1101_ENABLED`
- **对外接口**：统一挂在 `/api/v1/autonomy/*`，不新增并行控制面入口
