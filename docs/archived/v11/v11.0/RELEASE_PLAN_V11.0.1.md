# V11.0.1 Release Plan — Success-Rate First Capital Velocity & Autonomous Evolution OS

> AI量化交易闭环系统 — V11.0.1 规划说明  
> 文档版本：Draft v1.0 | 更新日期：2026-03-13  
> 当前状态：规划提案  
> 当前规划基线：V10.5.4 Signal Pipeline Integrity & Control-Plane Hardening  
> 核心命题：**在不牺牲成功率、不放宽风险上限的前提下，提高资金轮转效率，最大化净收益，并让系统具备自我感知、自我提升、自我进化能力，升级为新一代顶尖个人量化交易系统。**

---

## 0. 版本定位

### 0.1 一句话定义

V11.0.1 是一次 **Success-Rate First Capital Velocity & Autonomous Evolution OS** 升级：

> 让平台不只是“能交易、会风控、可观测”，而是能围绕**成功率优先的资金轮转**做实时资本编排，并基于自身表现、环境变化和执行反馈，持续完成**自我感知 → 自我诊断 → 自我优化 → 自我进化**。

### 0.2 为什么是 V11.0.1

如果说：

- **V10.5.3** 解决的是“利润控制回路”的方向问题；
- **V10.5.4** 解决的是“信号、状态、执行、审计真源统一”的底座问题；

那么 **V11.0.1** 要解决的问题是：

> 当控制平面已经统一之后，系统是否能够像一名顶尖职业交易员 + 交易总监 + 研究主管一样，持续识别哪里该重仓、哪里该快进快出、哪里该慢、哪里该停，并把资金、注意力和风险预算，自动分配给当前最值得拥有它们的机会。

这不是简单“加更多功能”，而是把平台从“机构级交易操作系统”进一步升级为：

1. **成功率优先的资本调度系统**：不是为了高换手而高换手，而是在高胜率、高净值效率场景下提升资金轮转。
2. **有自我认知的交易系统**：知道自己当前擅长什么、不擅长什么、哪里退化、哪里拥挤、哪里浪费了资金占用。
3. **会持续提升的交易系统**：能把失败、错过、滑点、持有过久、加减仓错误等问题沉淀成结构化改进动作。
4. **会受治理地进化的交易系统**：策略、参数、仓位模板、执行策略、市场优先级都能在证据链约束下自动演进。

---

## 1. 版本目标

### 1.1 北极星目标

围绕“**保证成功率前提下，提高资金轮转，最大化收益**”这一目标，V11.0.1 的北极星定义为：

- 更快识别**高把握度**机会；
- 更快释放被低效占用的资金与风险预算；
- 更快把资本轮转到**单位时间净收益更高**的机会；
- 更早感知策略、模型、执行、市场状态的退化；
- 更稳地在真实反馈中完成自我修正与版本级进化。

### 1.2 核心设计原则

| 原则 | 含义 | V11.0.1 解释 |
| ---- | ---- | ------------ |
| 成功率优先 | 所有轮转与提速必须建立在成功率、净 alpha、执行可达性基础上 | 不接受“高换手换来低质量收益” |
| 净收益优先 | 关注扣除滑点、冲击、拥挤、持有成本后的真实收益 | 不是看 gross return，而是看 unit-time net return |
| 资本占用敏感 | 任何仓位都必须回答“你占用这份资本是否值得” | 引入资本占用半衰期与席位再评估 |
| 系统自感知 | 系统必须知道自己当前是否健康、有效、退化、失真 | 自感知不是监控页，而是决策输入 |
| 进化受治理 | 任何自优化、自学习、自升级都必须可回放、可回退、可审计 | 不允许“黑箱自进化”直接接管实盘 |

### 1.3 北极星指标

| 指标 | 含义 | V11.0.1 目标方向 |
| ---- | ---- | ---------------- |
| Capital Velocity Efficiency | 单位风险预算在单位时间内创造的净收益效率 | 提升 |
| Success-Adjusted Turnover | 仅统计高质量成功交易后的有效轮转率 | 提升 |
| Net Return per Risk Minute | 每单位风险占用分钟创造的净收益 | 提升 |
| Idle Capital Ratio | 因低效持仓、等待、卡滞造成的无效资金占比 | 下降 |
| False Hold Rate | 本应减仓/换仓/退出却继续占位的比例 | 下降 |
| Self-Diagnosis Coverage | 可被系统自动解释和归因的问题覆盖率 | ≥ 90% |
| Improvement Loop Cycle Time | 从发现问题到形成优化动作上线 shadow 的时间 | 显著缩短 |
| Evolution Safety Coverage | 自优化/自进化动作具备 evidence + flag + rollback 的覆盖率 | 100% |

---

## 2. 版本主线

## M1. Success-Rate First Capital Velocity Engine

### M1 目标

把“资金轮转”从一个结果指标，升级为一个被系统主动优化的核心控制对象。

### M1 核心能力

#### 1. Capital Velocity Score（CVS）

为每个持仓、候选信号、待替换席位计算统一的资金轮转价值分数：

$$
CVS = WinProb \times ExpectedNetAlpha \times FillConfidence \times TimeEfficiency - RiskPenalty - FrictionPenalty - CrowdingPenalty
$$

其中：

- `WinProb`：成功率 / 命中率置信估计
- `ExpectedNetAlpha`：扣除预计执行成本、换手惩罚、体制折扣后的预期净 alpha
- `FillConfidence`：当前流动性与执行可达性评分
- `TimeEfficiency`：单位持有时间的收益效率（避免“慢收益占用快资金”）
- `RiskPenalty`：风险预算消耗、相关性、尾部暴露惩罚
- `FrictionPenalty`：滑点、市场冲击、换仓摩擦成本
- `CrowdingPenalty`：拥挤交易与共振衰减惩罚

#### 2. Capital Occupancy Half-Life

每个仓位新增“资本占用半衰期”概念，回答：

- 这个仓位的 alpha 是否正在衰减？
- 它继续占用资金是否仍优于新机会？
- 它处于“该持有、该减仓、该退出、该换仓”的哪个区间？

#### 3. Seat Rotation 2.0

在 V10.5.2 席位竞争基础上，升级为“成功率修正 + 时间效率修正”的席位轮转系统：

- 不仅比较谁的 `seat_value` 更高
- 还比较谁的**单位风险分钟净收益更高**
- 输出：
  - 为什么继续持有
  - 为什么减少占用
  - 为什么提前释放
  - 为什么等待更优 entry

#### 4. Turnover Guardrails

所有提速行为必须受四类约束：

- success floor（成功率下限）
- net alpha floor（净收益下限）
- friction ceiling（摩擦成本上限）
- replacement discipline（替换纪律）

系统禁止通过“更频繁但质量更差”的方式伪造高轮转。

### M1 交付结果

- 平台能够回答“为什么这笔资金现在应该继续留在这里 / 应该转去别处”。
- 轮转提效建立在成功率优先前提上，而不是牺牲胜率换速度。

---

## M2. Self-Perception Nervous System（自我感知神经系统）

### M2 目标

让平台具备对自身状态、市场状态、策略状态、执行状态、资本利用状态的持续感知能力，并把这种感知直接输入决策回路。

### M2 核心能力

#### 1. System Self-Perception Graph

建立统一自感知图谱，覆盖五类状态：

- **Market State**：当前市场体制、波动、流动性、热点密度、事件压强
- **Strategy State**：各策略当前胜率、衰减、拥挤度、适配体制、信号新鲜度
- **Execution State**：成交质量、预算超限、fill risk、延迟、冲击成本
- **Capital State**：资金利用率、风险预算占用、低效仓位、等待资本、轮转堵点
- **Model State**：模型置信度、校准偏差、异常漂移、推理稳定性、降级状态

#### 2. Meta-State Snapshot

为每次决策周期生成系统级元状态快照：

- 当前最强 alpha 来源是什么
- 当前最大的收益阻塞是什么
- 当前最大的失败风险是什么
- 当前最浪费资金的区域是什么
- 当前最值得加速轮转的市场/策略/账户是什么

#### 3. Self-Awareness Alerts

新增自感知告警，不仅提示系统故障，还提示“交易系统自身的行为问题”：

- 低效占位预警
- 胜率退化预警
- 过度等待预警
- 过度交易预警
- 执行成本失真预警
- 拥挤共振失效预警
- 参数过拟合风险预警

#### 4. Counterfactual Self-Reflection

每次关键决策都生成轻量反事实标签：

- 如果更快退出，结果会不会更好？
- 如果更晚入场，成功率是否更高？
- 如果仓位更小/更大，风险收益比是否更优？
- 如果不轮转，是否更优？

### M2 交付结果

- 系统从“看市场”升级为“同时看市场和自己”。
- 自感知结果不只是展示层，而会进入 `Portfolio / Risk / Execution / Governance` 的真实控制逻辑。

---

## M3. Self-Improvement Engine（自我提升引擎）

### M3 目标

让系统不仅知道哪里做得不好，还能自动形成带优先级的改进动作，并在 shadow / paper 环境验证后逐步进入主链。

### M3 核心能力

#### 1. Bottleneck Attribution Engine

对收益损失、轮转不畅和成功率下降做结构化归因，形成统一问题分类：

- alpha 不足
- 入场太早 / 太晚
- 持有太久
- 退出太慢
- 仓位过大 / 过小
- 执行成本过高
- 替换过慢
- 风险预算占用不合理
- 体制错配
- 模型置信度失真

#### 2. Improvement Backlog Auto-Generation

系统自动生成改进待办，不再只靠人工总结：

- 规则候选（Rule Candidate）
- 参数调整候选（Parameter Candidate）
- 仓位模板候选（Sizing Candidate）
- 执行策略候选（Execution Candidate）
- 晋级/降级建议（Promotion / Demotion Candidate）

每条候选都必须附带：

- 问题证据
- 预期收益改善
- 影响范围
- 风险说明
- 验证方式

#### 3. Improvement Lab

新增 Improvement Lab 工作台，统一管理：

- 问题榜单（Top draggers）
- 机会榜单（Top upgrade opportunities）
- 试验状态（Observe / Shadow / Challenger / Adopt / Rollback）
- 实验结果（成功率、净收益、轮转效率、回撤影响）

#### 4. Weekly Learning Pack

每周自动生成系统学习包，沉淀：

- 过去 7 天最值得保留的行为
- 最应停止的行为
- 最值得加速验证的改进动作
- 下周轮转重点方向
- 下周限制交易方向

### M3 交付结果

- “复盘”从被动总结升级为主动改进流水线。
- 平台会给出“下一步该怎么变得更好”，而不是只展示“之前发生了什么”。

---

## M4. Self-Evolution Governance（自我进化治理）

### M4 目标

让策略、参数、权重、执行模板、轮转纪律可以在证据链和风控边界内受治理地自动进化。

### M4 核心能力

#### 1. Strategy Genome & Evolution Ledger

为每个策略维护“进化谱系”：

- 当前版本
- 参数基因
- 适用体制
- 胜率分布
- 衰减速度
- 执行适配度
- 资本效率
- 升级 / 回滚历史

#### 2. Promotion / Demotion / Retirement Engine

策略、参数、执行模板进入统一演化状态机：

- `DISCOVERY`
- `SHADOW`
- `CHALLENGER`
- `ADOPTED`
- `LIMITED`
- `RETIRED`

任何升级或降级必须由以下证据触发：

- 成功率稳定性
- 体制适配性
- 净收益改进
- 轮转效率改进
- 执行质量稳定性
- 风险预算一致性

#### 3. Personal Style Alignment

在不走黑箱个性化的前提下，引入“个人交易风格对齐层”：

- 对收益波动容忍度建模
- 对持有周期偏好建模
- 对回撤容忍度建模
- 对轮转节奏偏好建模

让系统进化方向更贴近“个人顶尖量化系统”的实际使用语境，而不是泛化到机构多人共识模式。

#### 4. Evolution Safety Ring

所有自进化动作必须具备：

- feature flag
- adoption threshold
- automatic rollback
- human review hook
- audit trail

### M4 交付结果

- 平台具备“持续演化”的能力，但不牺牲可控性。
- 自我进化不再是抽象愿景，而是有状态机、有证据链、有回滚纪律的真实系统能力。

---

## M5. Next-Gen Personal Quant Workbench（新一代个人量化讲评台）

### M5 目标

把前端工作台升级为真正的“讲评台 / 指挥台 / 进化台”三位一体中枢，让用户像管理一支顶尖交易团队一样管理自己的量化系统。

### M5 核心能力

#### 1. Capital Velocity Cockpit

新增或升级核心视图，统一展示：

- 当前资金占用地图
- 高质量轮转机会队列
- 低效席位清单
- 风险预算释放路径
- unit-time net return 排行
- “应快 / 应慢 / 应停”建议

#### 2. Self-Perception Board

集中展示系统当前自感知结论：

- 我现在最强的赚钱模式是什么
- 我现在最大的失误来源是什么
- 我现在最拥挤、最脆弱的区域是什么
- 我现在最应该收缩还是扩张
- 我现在最适合哪种执行节奏

#### 3. Improvement & Evolution Board

集中展示：

- 本周 Top 5 改进建议
- 当前 shadow 实验
- 晋级 / 回滚建议
- 已验证可采纳的规则候选
- 自进化动作的证据链与风险提示

#### 4. Copilot as CIO/COO

让 Copilot 不只是问答入口，而是担任：

- **CIO（Chief Investment Officer）**：解释当前资本分配逻辑、策略优先级、最强 alpha 区域
- **COO（Chief Operating Officer）**：解释当前系统运行瓶颈、执行质量、数据健康、轮转阻塞
- **Learning Coach**：解释最近系统学到了什么、下一步会尝试什么、为什么建议这样演进

### M5 交付结果

- 用户看到的不再是分散页面，而是一套真正围绕“赚钱能力 + 学习能力 + 演化能力”的顶尖个人量化操作台。
- 平台具备“讲得清、看得透、改得动、进得化”的完整工作台体验。

---

## 3. 前端规划要点

V11.0.1 的前端原则不是继续加页面，而是围绕“讲评台”升级现有核心工作台：

1. **`/alpha-lab`** → Alpha Truth + Success-Adjusted Opportunity Console
2. **`/portfolio`** → Capital Velocity & Seat Rotation Console
3. **`/execution-policy`** → Fill Confidence & Cost Discipline Console
4. **`/governance/pipeline`** → Improvement / Evolution Governance Board
5. **`/autonomy` / Watchtower** → Self-Perception & System Reflex Console
6. **`/war-room`** → 从实时指挥视图升级为“资本轮转 + 系统自感知”总控台

统一设计要求：

- 所有关键结论同时显示：
  - 结果值
  - 解释字段
  - 数据质量
  - 置信度
  - 来源类型
  - 推荐动作
  - 证据链状态
- 所有“建议加速轮转”的结论必须同时显示“为什么不会伤害成功率”。
- 所有“建议改进 / 进化”的结论必须可下钻到证据与实验记录。

---

## 4. 后端实施重点

### 4.1 Capital Velocity

重点升级：

- `capacity_arbiter.py`
- `risk_gate_service.py`
- `execution_policy_service.py`
- `autonomous_engine.py`
- `trade_attribution_engine.py`

新增能力：

- capital velocity score
- capital occupancy half-life
- success-adjusted turnover metrics
- unit-time net return attribution

### 4.2 Self-Perception

重点升级：

- `signal_intelligence_service.py`
- `execution_microscope_service.py`
- `research_service / v1051_research_service.py`
- `autonomy health / system monitor` 相关服务

新增能力：

- meta-state snapshot
- self-awareness alerts
- counterfactual self-reflection tags
- capital blockage diagnostics

### 4.3 Self-Improvement

重点升级：

- `decision_post_mortem_service.py`
- `insight_service.py`
- `ab_test_engine.py`
- `governance / pipeline` 相关 service

新增能力：

- bottleneck attribution engine
- rule/parameter/sizing/execution candidates
- improvement backlog auto-generation
- weekly learning pack

### 4.4 Self-Evolution

重点升级：

- governance pipeline
- strategy registry / experiment ledger
- promotion / rollback state machine

新增能力：

- strategy genome
- evolution ledger
- promotion / demotion / retirement engine
- style alignment constraints

---

## 5. Feature Flags（建议）

- `CAPITAL_VELOCITY_V1101_ENABLED`：控制 capital velocity score、capital occupancy half-life、轮转约束是否进入主链
- `SELF_PERCEPTION_V1101_ENABLED`：控制 meta-state snapshot、自感知告警、自反事实标签是否启用
- `IMPROVEMENT_ENGINE_V1101_ENABLED`：控制 bottleneck attribution、改进待办自动生成、Improvement Lab 是否启用
- `EVOLUTION_GOVERNANCE_V1101_ENABLED`：控制 strategy genome、演化状态机、晋级/回滚自动建议是否启用
- `STYLE_ALIGNMENT_V1101_ENABLED`：控制个性化交易风格约束是否参与排序、晋级和仓位模板生成

---

## 6. 统一验收标准

### 6.1 Success-Rate First Capital Velocity

- [ ] 每个持仓 / 候选信号都可输出 `capital_velocity_score`
- [ ] 系统可解释“为什么这笔资本继续持有 / 应释放 / 应轮转”
- [ ] 所有轮转建议同时显示成功率影响、净收益影响与摩擦成本影响
- [ ] 资金轮转效率提升不以成功率显著下降为代价

### 6.2 Self-Perception

- [ ] 每个决策周期可生成系统级 `meta-state snapshot`
- [ ] 系统可自动识别低效占位、成功率退化、执行成本失真、拥挤失效等问题
- [ ] 自感知结论已进入 Portfolio / Risk / Execution / Governance 的真实控制逻辑

### 6.3 Self-Improvement

- [ ] 系统能自动生成改进候选，并附带证据、预期收益与验证方案
- [ ] `Improvement Lab` 可追踪每个改进候选从发现到 shadow 的完整流程
- [ ] 周级学习包能输出“该保留什么 / 该停止什么 / 该尝试什么”

### 6.4 Self-Evolution

- [ ] 策略、参数、执行模板具备统一演化状态机与证据链
- [ ] 晋级、降级、退役建议可解释且支持回滚
- [ ] 所有自进化动作具备 feature flag、phase rollout 与审计记录

### 6.5 Workbench 体验

- [ ] 讲评台可同时回答“现在怎么赚钱、哪里在失分、接下来怎么改、为什么这样演化”
- [ ] 所有关键建议可下钻到数据、解释、证据和历史实验
- [ ] Copilot 可基于系统当前元状态提供 CIO / COO / Learning Coach 三类解释

---

## 7. 发布策略建议

### Stage A — Observe

- 只计算 capital velocity、自感知、自提升候选与演化建议
- 不改变 live 执行行为
- 核心目标：验证指标与解释是否可信

### Stage B — Shadow Optimization

- 在 shadow / paper 中启用 capital rotation、improvement ranking、evolution suggestion
- 对比旧逻辑：
  - 成功率差异
  - 资金占用差异
  - 净收益差异
  - 执行成本差异

### Stage C — Semi Adoption

- 在有限真实账户 / 有限策略 / 有限市场启用 capital velocity 主链
- 自提升建议仍需人工确认或治理批准

### Stage D — Guided Evolution

- 允许有限类别的低风险优化动作自动进入主链
- 例如：执行参数微调、持有时长阈值微调、候选排序权重微调
- 仍保留硬回滚机制

### Stage E — Full Autonomous Evolution

- 在满足证据与安全覆盖条件后，允许平台对部分策略和执行模板进行受治理自动演化
- 仍不允许绕过风控和治理硬门槛

---

## 8. 非目标（明确边界）

V11.0.1 当前**不以**下列事项为主目标：

1. 单纯扩充更多页面数量
2. 盲目提升交易频率
3. 放宽 VaR / Stress / Position 限制换取收益
4. 在没有证据链的情况下自动修改核心风险参数
5. 先做多用户平台化而削弱“个人顶尖量化系统”这一主线

---

## 9. 最终判断

V11.0.1 的价值，不在于把系统做得更复杂，而在于把平台真正推进到一个更高等级：

> **它不仅会交易，还会感知自己；不仅会复盘，还会形成改进动作；不仅会优化参数，还会在治理框架内持续演化。**

如果 V10.5.4 解决的是“控制平面必须先统一”，那么 V11.0.1 要解决的就是：

> **如何让这套统一后的控制平面，成为一个成功率优先、资金轮转高效、能自我提升并持续进化的顶尖个人量化交易系统。**
