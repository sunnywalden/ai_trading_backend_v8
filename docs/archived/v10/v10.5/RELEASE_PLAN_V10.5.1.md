# V10.5.1 版本规划 — 从“功能完整”走向“机构级交易操作系统”

> AI量化交易闭环系统 — V10.5.1 版本规划
> 文档版本：Draft v1.0 | 制定日期：2026-03-08
> 基础版本：V10.4.3
> 核心命题：把平台从“能自主交易、能看见全链路”推进到“能被严格验证、可控放量、能持续迭代 alpha”。

---

## 0. 华尔街顶尖量化团队视角：当前平台的真实位置

如果以顶级量化团队的标准看，这个平台已经具备三个难得的基础：

1. 决策链路已经高度产品化。
2. 交易生命周期、审计链路、系统可观测性已经明显强于大多数个人交易系统。
3. 风险降低类订单已具备独立快速通道，避免了“该平仓时反而被系统卡住”的结构性缺陷。

但距离“可安全放大资金规模”的机构级系统，还差四个核心层：

1. Alpha 真相层不足。
当前系统已经有信号融合、因子权重、自适应更新和事后归因，但仍偏向“信号治理”而不是“预测能力治理”。系统知道哪些信号被放行，却还不够知道哪些预测在净交易成本后真正赚钱、赚钱来源是否稳定、是否只是在吃 Beta 或样本噪声。

2. 组合构建仍偏简化。
现有优化器具备 Markowitz、Risk Parity、Kelly，但约束集仍偏轻，缺少 turnover、liquidity、capacity、beta/factor budget、sector bucket、crowding budget 等机构级约束。

3. 执行层有路由，但缺少 execution policy。
现在已经有自动执行和 TWAP/VWAP/市价选择，但还没有形成完整的“订单紧急度、参与率、滑点预算、child order 调度、撤改单策略、成交后再锚定”的统一执行策略框架。

4. 回测与上线治理还不够严谨。
回测层已经能跑，但更接近策略原型验证，而不是 production research stack。缺少 purged walk-forward、事件日隔离、容量回放、交易成本曲线、shadow live、paper/live 一致性度量。

一句话判断：

> V10.4.3 已经把“能跑起来”解决得很好，V10.5.1 应该解决“这套系统为什么能长期跑、凭什么能放大风险预算”。

---

## 1. 当前机制的优点与短板

### 1.1 值得保留并继续强化的优点

#### A. 信号治理框架已经成型

- `SignalQualityFunnel` 五层漏斗、Conviction Score、Ghost Trade、审计日志，说明系统已经不是“有信号就下单”，而是具备 signal curation 能力。
- `AutonomousEngine` 已把 `STANDARD / FAST_CLOSE / FORCE_EXIT` 路由显式化，降低了自主执行中的黑箱风险。

#### B. 风险边界和可观测性意识较强

- `RiskGateService` 有明确的仓位、VaR、压力测试、日交易数、熔断限制。
- 前后端都已经建立强观测能力：Lifecycle、Order Book、Execution Microscope、Risk Cluster、System Monitor、War Room。

#### C. 系统设计已经具备“审计员视角”

- 这对 FULL 模式非常关键。很多系统只会做 dashboard，不会做 evidence chain；你们已经把 provenance、intent、risk bypass、agent log 等基础打下来了。

### 1.2 顶级量化团队会立即指出的短板

#### A. 风险模型仍然过于教学化

- `RiskGateService` 当前 VaR 估算仍使用固定 30% 年化波动率近似，压力测试仍以单一 GFC -50% 冲击为主。
- 这适合 P0 护栏，不适合真实风险预算与资本配置。

#### B. 回测层仍然偏原型验证

- `BacktestRunner` 仍存在等权分配、策略适配有限、alpha 基准简化、成本回放不足等问题。
- 这会导致“研究端看起来很好，实盘后发现容量与成本吃掉大半 alpha”。

#### C. 执行层还没有把“交易”当成独立 alpha 保存问题

- 订单执行目前主要是 MARKET / LIMIT 与简单价格偏置。
- 顶级团队会把 execution shortfall 当作和 signal quality 同等级别的核心对象管理，而不是下单后的附属指标。

#### D. 组合优化缺少真实世界约束

- 当前优化器以 long-only、单标的上限、协方差矩阵为主。
- 真实可交易组合还要加入：成交量占比、行业篮子预算、相关性簇、事件暴露、beta 漂移、持仓拥挤度、预期 turnover 成本。

#### E. 平台更像“交易控制塔”，还不像“研究生产系统”

- 现在最强的是观测与控制。
- 下一阶段需要把研究结果、成本、风险、上线规则连成一条“真相生产线”。

---

## 2. V10.5.1 版本目标

### 2.1 版本定位

V10.5.1 不是一个以 UI 为主的版本，而是一个以“策略质量、执行质量、上线纪律”三件事为核心的版本。

### 2.2 成功标准

如果 V10.5.1 成功，平台应达到以下状态：

1. 每个信号维度、每个策略、每种执行方式都能回答“净成本后是否赚钱”。
2. 每笔订单在发出前都知道预期冲击成本、参与率和执行紧急度。
3. 每个组合建议都能解释 marginal risk、marginal alpha、liquidity usage、turnover budget。
4. 每个新规则上线前都有 shadow 证据，而不是只靠 paper 胜率。
5. 系统出现数据滞后、模型退化、成交异常时，能够自动降级而不是继续盲跑。

---

## 3. V10.5.1 核心功能规划

## M1. Alpha Truth Stack

### 为什么这是第一优先级

顶级团队不会先问“界面是否更炫”，而会先问：

> 你的 alpha 是什么？在什么 regime 有效？净成本后还剩多少？衰减速度如何？

### 功能清单

#### 1. Strategy Scorecard 2.0

新增统一策略评分卡，按策略、子策略、信号维度输出：

- gross alpha
- net alpha
- hit rate
- payoff ratio
- turnover
- average holding period
- implementation shortfall drag
- regime-conditioned performance
- crowding penalty
- capacity utilization

#### 2. Factor Registry 与 Label Integrity

把当前六维信号、策略输出、宏观与事件特征纳入统一注册表：

- 因子定义版本化
- 特征生成时间戳固化
- label 生成规则固化
- 防止 look-ahead / leakage

#### 3. Purged Walk-Forward Backtest

把现有 Walk-Forward 升级为更严格版本：

- train/validation/test 分层
- earnings/FOMC/CPI/NFP 事件窗口 purge
- overlapping label 去污染
- regime bucket 分组报告

#### 4. Shadow Portfolio

对被漏斗拒绝、被风控拒绝、被执行策略降级的信号建立影子组合：

- rejected by funnel shadow book
- rejected by risk shadow book
- rejected by execution shadow book

目的不是放行它们，而是验证当前护栏是否过强、是否错杀 alpha。

### 验收标准

- 任一策略可查看近 20/60/120 个交易日 gross/net alpha 与 regime 分布。
- 任一信号维度可查看命中率、收益分布、衰减曲线、交易成本后剩余 alpha。
- Backtest 报告必须区分 gross return 与 net return。
- Shadow book 能输出“错杀率”和“保护收益”两项核心指标。

---

## M2. Portfolio Construction 2.0

### 为什么要做

现在的组合优化已经有数学外形，但还没有足够多的现实约束。顶级团队看组合，不只看最优解，还看“这个解是否真能交易、能不能持续持有、会不会把风险预算误用在噪音上”。

### 功能清单

#### 1. Risk Budget Tree

新增分层风险预算：

- portfolio gross exposure budget
- single-name risk budget
- sector risk budget
- regime risk budget
- event risk budget
- liquidity budget

#### 2. Marginal Contribution Dashboard

组合层新增以下指标：

- marginal VaR
- marginal ES
- marginal turnover
- marginal expected alpha
- marginal crowding risk

#### 3. Liquidity-Aware Sizing

仓位 sizing 不再只看账户权益比例，而加入：

- ADV 占比限制
- expected participation rate
- bid/ask spread proxy
- lot size / odd-lot / market-specific constraints

#### 4. Covariance 与暴露治理升级

新增：

- shrinkage covariance
- factor exposure constraints
- beta drift guard
- correlation cluster cap
- sector bucket cap

### 验收标准

- 每个建议仓位都能显示流动性占用、边际风险、边际 alpha。
- 组合优化输出必须带上 turnover budget 与 liquidity budget。
- 任何超出 sector/factor/liquidity budget 的提案必须被明确解释为 rejected 或 scaled down。

---

## M3. Execution Policy Engine

### 为什么要做

当前系统已有执行路由，但缺少机构级执行策略层。顶级团队不会接受“信号是好的，但执行随缘”。

### 功能清单

#### 1. Execution Policy DSL

为订单建立统一执行政策对象：

- urgency: low / medium / high / forced
- max_participation_rate
- slippage_budget_bps
- child_order_interval
- cancel_replace_policy
- limit_offset_policy
- closing_override_policy

#### 2. Algo Router 2.0

扩展当前 MARKET / LIMIT / TWAP / VWAP 逻辑，新增：

- POV 风格参与率执行
- auction close / open 偏好
- event mode execution
- opening range / closing window execution template

#### 3. Pre-Trade Cost Model

下单前先估计：

- spread cost
- market impact
- timing risk
- opportunity cost

并把成本预测反馈给组合构建层，形成“信号强，但成本更高，不值得下”的真实拒绝逻辑。

#### 4. Post-Trade Replay

把执行结果回放给策略与执行模块：

- arrival vs fill
- child-order timeline
- cancel/replace count
- fill quality by regime/time bucket

### 验收标准

- 任一订单都有 execution policy 快照。
- 下单前必须生成预估成本，不再是纯规则选择算法。
- 执行质量报告新增按时段、标的流动性分桶、紧急度分桶的表现分析。

---

## M4. Live Safety and Model Degradation Guard

### 为什么要做

FULL 模式的核心问题不是“会不会下错一笔单”，而是“当环境变坏时系统能否自己知道该收缩”。

### 功能清单

#### 1. Model Degradation Monitor

对以下对象做实时退化监控：

- strategy hit rate drift
- confidence calibration drift
- execution cost drift
- feature freshness drift
- broker reject spike

#### 2. Adaptive Autonomy Throttle

当退化超阈值时自动降级：

- FULL → SEMI
- SEMI → ADVISORY
- 某些策略停用
- 某些市场只允许减仓

#### 3. Data Freshness Kill Matrix

建立严格的数据陈旧矩阵：

- quote stale
- position stale
- event calendar stale
- factor snapshot stale
- market regime stale

不同 stale 级别触发不同动作：继续、降级、冻结新开仓、仅允许平仓。

#### 4. Broker Execution Integrity Guard

监控：

- reject ratio
- cancel ratio
- stale order ack
- duplicate order risk
- partial fill aging

### 验收标准

- 系统可在模型退化、数据陈旧、券商异常三类场景自动降级。
- 降级动作必须写入审计日志，并在 `/system` 与 `/autonomy` 直接可见。
- 所有 kill switch 都要区分“禁止开仓”和“允许减仓/平仓”。

---

## M5. Research-to-Live Governance

### 为什么要做

顶级团队的核心不是模型更神，而是上线纪律更严。V10.5.1 必须补上从研究到 live 的发布治理链路。

### 功能清单

#### 1. Strategy Promotion Pipeline

新增统一晋级流程：

- research candidate
- sandbox validated
- shadow live
- paper approved
- limited live
- full live

#### 2. Change Attribution

每次参数或规则变动都必须回答：

- 是谁改的
- 改了什么
- 预期提升什么
- 上线后是否真的提升

#### 3. Experiment Ledger

将 ABTest 扩展为实验总账：

- hypothesis
- variant definition
- cost-adjusted outcome
- significance
- rollout decision
- rollback reason

### 验收标准

- 新策略或参数变更必须进入 promotion pipeline 才能进入 limited live。
- 所有实验都能追溯上线结论与回滚原因。
- 任何线上 alpha 变化都能追溯到策略、执行、风控或市场环境中的至少一个主因。

---

## 4. 前端规划要点

V10.5.1 前端不应追求“再多几个页面”，而应服务于研究真相与交易纪律。

### 4.1 新增或升级页面

1. Alpha Lab
统一展示策略净 alpha、衰减、容量、regime 分组、shadow book 对照。

2. Portfolio Construction Console
展示 risk budget tree、marginal contribution、liquidity usage、scaled-down reason。

3. Execution Policy Console
展示 execution policy、预估成本、参与率、撤改单、child-order timeline。

4. Promotion Pipeline Board
展示策略从 research 到 live 的晋级状态、阻塞原因与证据。

### 4.2 前端设计原则

- 保持当前 Bloomberg 风格，不再横向扩页。
- 优先把现有 observability 资产整合为“可决策面板”。
- 所有关键建议必须显示“why now / why size / why not larger / why not live”。

---

## 5. 版本优先级排序

如果只能做 3 件事，我建议 V10.5.1 只做下面三件：

1. Alpha Truth Stack
因为没有净成本后的真相，后面所有优化都有可能只是让系统更复杂。

2. Execution Policy Engine
因为交易成本会直接吃掉 alpha，这比再做一个新策略页重要得多。

3. Live Safety and Model Degradation Guard
因为 FULL 模式下，最重要的是系统知道自己什么时候不该继续扩张风险。

组合优化 2.0 与 Promotion Pipeline 可以作为同版并行项，但优先级略低于以上三项。

---

## 6. 对现有代码与机制的直接建议

### 6.1 应继续保留的机制

- 保留信号漏斗与 Ghost Trade，不要回退到粗放式“多信号多下单”。
- 保留 FAST_CLOSE / FORCE_EXIT 双快通道，这是正确方向。
- 保留 Execution Microscope、Signal Intelligence、Risk Cluster 这类观测资产，并把它们向研究决策回灌。

### 6.2 应优先升级的机制

- 把简化 VaR 和单一压力测试升级成分层风险预算与场景库。
- 把回测从“验证能不能跑”升级到“验证净成本后是否成立”。
- 把优化器从“权重求解器”升级到“受流动性与风险预算约束的组合构建器”。
- 把执行器从“下单器”升级到“执行政策执行器”。

### 6.3 暂时不建议优先做的内容

- 不建议在 v10.5.1 把重点放在新增更多 AI 页面。
- 不建议先做更多策略种类扩张。
- 不建议先做移动端扩张。

原因很简单：

> 现在平台缺的不是“看见更多”，而是“确认哪些东西真的有 alpha，且能被稳定交易出来”。

---

## 7. V10.5.1 里程碑建议

### Milestone A: 研究真相基线

- Strategy Scorecard 2.0
- gross/net alpha 分离
- purged walk-forward
- shadow portfolio

### Milestone B: 执行与组合升级

- execution policy engine
- pre-trade cost model
- liquidity-aware sizing
- risk budget tree

### Milestone C: 上线治理闭环

- model degradation monitor
- adaptive autonomy throttle
- promotion pipeline
- experiment ledger

---

## 8. Epic 拆分

### Epic A. 后端 Epic

#### A1. Alpha Truth Services

目标：把“信号被放行”升级为“信号净成本后是否真实有效”。

后端任务：

- 新增 `strategy_scorecard_service.py`，按策略、子策略、信号维度输出 gross/net alpha、hit rate、turnover、holding period、regime performance。
- 新增 `factor_registry_service.py`，统一管理因子定义、版本、特征生成时间、label 规则与数据质量标记。
- 升级 `signal_intelligence_service.py`，补齐 alpha decay、regime-conditioned IC、capacity bucket 分析。
- 新增 `shadow_portfolio_service.py`，统一管理 funnel reject、risk reject、execution reject 三类 shadow book。
- 新增 `/api/v1/alpha-lab/*` 路由组，暴露 scorecard、factor registry、shadow book、regime breakdown。

#### A2. Portfolio Construction 2.0

目标：把优化器从权重求解器升级为真实可交易组合构建器。

后端任务：

- 升级 `app/engine/portfolio/optimizer.py`，加入 turnover、ADV、sector、factor、beta、correlation cluster 约束。
- 新增 `risk_budget_service.py`，维护 portfolio / sector / factor / event / liquidity 多层预算。
- 新增 `liquidity_sizing_service.py`，在仓位建议中输出 ADV 占比、参与率、市场约束、odd-lot 规则。
- 新增 `portfolio_marginal_contribution_service.py`，计算 marginal VaR、marginal ES、marginal alpha、marginal turnover。
- 扩展 `/api/v1/portfolio/*`，新增 budget、marginal contribution、scaled-down reason 相关端点。

#### A3. Execution Policy Engine

目标：把执行层从算法路由升级为执行策略系统。

后端任务：

- 新增 `execution_policy_service.py`，为每笔订单生成 policy snapshot。
- 新增 `pretrade_cost_model_service.py`，预测 spread、impact、timing、opportunity cost。
- 升级 `twap_vwap_service.py` 与 `order_executor.py`，支持 urgency、participation rate、child-order schedule、cancel/replace policy。
- 新增 `execution_replay_service.py`，按 child-order timeline 回放成交并形成执行归因。
- 扩展 `/api/v1/execution/*` 或 `/api/v1/observability/execution-*`，输出 policy、cost estimate、replay、bucketized quality。

#### A4. Live Safety & Model Degradation Guard

目标：让系统知道什么时候该自动收缩风险。

后端任务：

- 新增 `model_degradation_monitor_service.py`，跟踪 strategy hit rate drift、ECE drift、execution cost drift、broker reject spike。
- 新增 `data_freshness_guard_service.py`，维护 quote/position/event/factor/regime stale matrix。
- 新增 `autonomy_throttle_service.py`，根据退化等级自动执行 FULL → SEMI → ADVISORY 降级。
- 升级 `autonomous_engine.py` 与 `/api/v1/autonomy/status`，暴露降级原因、当前 throttle、kill-switch 级别。
- 扩展 `/api/v1/system-monitor/*`，增加 degradation 与 freshness 视图。

#### A5. Research-to-Live Governance

目标：让策略、参数、执行规则上线前都有证据链。

后端任务：

- 新增 `promotion_pipeline_service.py`，管理 research candidate → shadow live → paper → limited live → full live。
- 新增 `experiment_ledger_service.py`，把 ABTest 升级为完整实验账本。
- 新增 `change_attribution_service.py`，记录策略/参数/执行规则变更与上线后结果。
- 扩展 `backtest_runner`、`paper_trading_service`、`insight_service`，接入 promotion pipeline。
- 新增 `/api/v1/governance/*` 路由组，暴露 pipeline、experiment ledger、rollout/rollback evidence。

### Epic B. 前端 Epic

#### B1. Alpha Lab

目标：把策略有效性从静态报表升级为可决策工作台。

前端任务：

- 新增 `/alpha-lab` 路由，作为研究真相一级入口。
- 页面布局包含 Strategy Scorecard、Signal Decay、Regime Breakdown、Shadow Book Compare 四个主面板。
- 支持策略、标的、信号维度、市场体制、时间窗口多维筛选。
- 新增 gross/net alpha 切换、成本拖拽对比、错杀率与保护收益对照视图。

#### B2. Portfolio Construction Console

目标：让组合建议具备机构级解释性。

前端任务：

- 升级 `/portfolio` 页面为多 Tab 控制台：Target Weights、Risk Budget、Marginal Contribution、Liquidity Usage。
- 新增 risk budget tree、marginal contribution waterfall、sector/factor/cluster 约束可视化。
- 对所有 scaled-down / rejected 持仓建议显示明确原因，而不是只给最终权重。

#### B3. Execution Policy Console

目标：让执行成为一等公民，而不是订单详情附属页。

前端任务：

- 新增 `/execution-policy` 页面或合并进 `/order-book` / `/observability/execution` 的高级视图。
- 展示 execution policy snapshot、pre-trade cost card、child-order timeline、cancel/replace 明细、bucketized fill quality。
- 新增 urgency、participation、slippage budget、policy version 徽章体系。

#### B4. Promotion Pipeline Board

目标：把研究上线纪律可视化。

前端任务：

- 新增 `/governance/pipeline` 页面，采用 Kanban 展示 strategy promotion stages。
- 展示每个候选策略的证据卡：backtest、shadow live、paper、limited live、rollback reason。
- 新增 experiment ledger 视图，支持按 hypothesis、owner、significance、status 筛选。

#### B5. 导航与信息架构调整

目标：新增功能但不回到“页面膨胀”。

前端任务：

- 在“研究 & 分析”中新增 Alpha Lab。
- 在“交易中枢”或“研究 & 分析”中重构 Portfolio 页面为 Portfolio Construction Console。
- 在“AI 洞察 & 系统”中新增 Governance / Promotion Pipeline 入口，或作为 AI 进化页的二级 Tab。
- 保持一级导航仍不超过 4 组，不新增孤立导航分组。

### Epic C. 数据与作业 Epic

#### C1. 新增数据表与快照

建议新增表：

- `strategy_scorecard_snapshots`
- `factor_registry`
- `feature_generation_log`
- `shadow_portfolio_entries`
- `risk_budget_snapshots`
- `execution_policy_snapshots`
- `pretrade_cost_estimates`
- `execution_replay_logs`
- `model_degradation_snapshots`
- `promotion_pipeline_runs`
- `experiment_ledger_entries`

#### C2. 新增定时任务

新增 Job：

- `daily_strategy_scorecard_refresh`
- `daily_alpha_decay_refresh`
- `post_close_shadow_portfolio_mark`
- `intraday_model_degradation_scan`
- `intraday_data_freshness_scan`
- `daily_pretrade_cost_calibration`
- `nightly_execution_bucket_aggregation`
- `promotion_pipeline_review_job`

#### C3. 数据契约与质量要求

数据/作业任务：

- 所有新快照都要带 `as_of`, `data_quality`, `calculation_version`。
- 所有特征与标签都要记录 `generated_at`, `source_window_end`, `leakage_guard_status`。
- 所有 execution replay 数据都要可追溯到 parent order 与 child order。
- 所有 shadow 数据都必须能区分 reject 来源：funnel / risk / execution / governance。

### Epic D. 测试与验收 Epic

#### D1. 后端测试

- 单元测试覆盖新增服务的核心计算逻辑。
- 集成测试覆盖 portfolio constraints、execution policy routing、degradation-triggered throttle。
- 回归测试覆盖 fast close / force exit 与新 kill-switch 共存场景。

#### D2. 前端测试

- 组件测试覆盖 Alpha Lab、Portfolio Console、Execution Policy Console、Promotion Pipeline Board。
- E2E 测试覆盖筛选、联动钻取、降级状态展示、shadow/live 证据链浏览。
- 移动端不做新增目标，但需保证新增核心页面在桌面端优先完成，无明显断裂。

#### D3. 数据与作业测试

- Job 幂等性测试。
- 快照一致性测试。
- shadow/live 数据归因一致性测试。
- feature/label 时间窗口防泄漏测试。

---

## 9. 统一验收清单

### 9.1 后端验收

- [ ] 任一策略、子策略、信号维度均可返回 gross alpha 与 net alpha 双口径指标。
- [ ] Purged Walk-Forward 支持事件窗口 purge、regime bucket 报告、gross/net return 分离。
- [ ] Portfolio 输出包含 risk budget、liquidity usage、marginal contribution、scaled-down reason。
- [ ] 每笔订单在提交前均生成 execution policy snapshot 与 pre-trade cost estimate。
- [ ] execution replay 能回放 child-order timeline，并按流动性/紧急度分桶聚合质量。
- [ ] 模型退化、数据陈旧、券商异常三类风险均可触发自主度降级或冻结新开仓。
- [ ] promotion pipeline 能记录从 shadow live 到 limited live 的每个晋级节点与回滚证据。

### 9.2 前端验收

- [ ] `/alpha-lab` 可查看策略净 alpha、衰减、shadow 对照、regime 表现。
- [ ] `/portfolio` 或新控制台能展示 risk budget tree、marginal contribution、liquidity usage。
- [ ] `/execution-policy` 或执行高级视图能展示 policy、cost estimate、replay timeline。
- [ ] `/governance/pipeline` 能按阶段查看候选策略与 rollout/rollback 证据。
- [ ] 新页面不导致一级导航超过 4 组，不回退到页面膨胀模式。

### 9.3 数据与作业验收

- [ ] 所有新快照表均支持 `as_of / data_quality / calculation_version`。
- [ ] 所有新 Job 可幂等重跑，不产生重复主结果。
- [ ] shadow 数据与 live 数据可按同一策略、同一信号维度、同一体制对齐比较。
- [ ] feature 与 label 时间戳完整，能证明无前视偏差。

### 9.4 业务结果验收

- [ ] 任一策略都能回答“净成本后是否赚钱”。
- [ ] 任一持仓建议都能回答“为什么是这个仓位，而不是更大或更小”。
- [ ] 任一订单都能回答“为什么用这个执行策略，而不是另一种”。
- [ ] 任一上线中的新策略都能回答“为什么允许进入 live，若失败又为何回滚”。

---

## 10. 建议实施顺序

### Sprint 1

- Alpha Truth Stack 基础表与 API
- Strategy Scorecard 2.0
- Shadow Portfolio 基础能力

### Sprint 2

- Portfolio Construction 2.0 基础约束
- Liquidity-Aware Sizing
- Portfolio Console 前端首版

### Sprint 3

- Execution Policy Engine
- Pre-Trade Cost Model
- Execution Policy Console

### Sprint 4

- Model Degradation Guard
- Adaptive Autonomy Throttle
- Promotion Pipeline 与 Experiment Ledger

---

## 11. 最终判断

从顶级量化团队视角看，这个平台最值得肯定的地方，不是“做了 AI”，而是已经开始把 AI、自主交易、执行、风控、可观测性编织成一个统一系统。

但下一步的胜负手不在于继续做更多功能，而在于把三个问题做硬：

1. alpha 是否真实。
2. alpha 是否能在真实执行成本后保留下来。
3. 当 alpha 退化时系统是否会自动缩表、自我降级。

所以，V10.5.1 最正确的方向不是“更花哨的智能交易平台”，而是：

> 把它变成一个有研究纪律、有执行纪律、有上线纪律的机构级交易操作系统。