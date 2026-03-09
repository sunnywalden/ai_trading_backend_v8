# V10.5.2 版本规划 — 从“信号筛选”升级到“席位竞争式组合准入”

> AI量化交易闭环系统 — V10.5.2 规划说明
> 文档版本：Draft v1.0 | 更新日期：2026-03-09
> 当前状态：规划中
> 基础版本：V10.5.1
> 核心命题：把“持仓上限”从刚性拒绝规则，升级为面向组合收益质量的动态席位分配机制。

---

## 0. 华尔街顶尖量化 PM / 产品经理视角：系统现状判断

如果用顶级量化平台的标准审视当前系统，V10.5.1 已经具备四个强项：

1. 信号质量治理已经明显优于普通零售交易系统。`SignalQualityFunnel`、`Conviction Score`、`Ghost Trade` 和完整审计链，说明系统不是“见信号就买”。
2. 风险降低优先路径已经建立。`REDUCE/EXIT/FORCE_EXIT` 快速通道，解决了“该减仓时反而被门控卡住”的典型结构性错误。
3. 持仓生命周期与执行可观测性已经具备平台级雏形。系统能解释信号、风险门、执行路径、持仓状态与事后归因。
4. 研究、交易、风险、观察四条链路已经连起来，产品形态不再是简单策略工具，而是交易操作系统。

但如果站在“可放大资金规模”的机构视角，系统当前还存在一个关键缺口：

> 在席位稀缺时，系统仍然主要在做“信号过滤”，而不是“组合层的优胜劣汰”。

这会直接带来三类问题：

1. 当持仓数达到上限时，`SignalQualityFunnel` Layer 2 当前会直接拒绝新开仓信号，这是一种静态容量门，而不是动态资本再分配。
2. `PositionRebalanceMonitor` 目前只在“持仓已经超限”后才异步产生 EXIT 信号，属于事后纠偏，不是实时准入决策。
3. 当前系统虽然同时有“信号质量分”和“持仓评分”，但两者没有被放入同一个统一排序框架中做席位竞争。

在顶级量化平台里，席位本身就是稀缺资源。真正的问题不是“有没有新信号”，而是：

> 新信号相对于当前持仓，是否更值得占用有限席位与风险预算？

V10.5.2 就是解决这个问题。

---

## 1. 版本定位

### 1.1 一句话定义

V10.5.2 是一个“组合准入与替换”版本，不再把持仓上限理解为简单硬门槛，而是把它升级为一套实时的席位竞争机制。

### 1.2 版本目标

当当前持仓标的数达到或超过上限时，系统不再直接拒绝新信号，而是：

1. 将当前持仓与新信号统一放入同一候选池。
2. 用统一质量框架对二者做横向排序。
3. 计算需要淘汰的末位对象数量：

$$
N = 持仓标的数 + 新信号数 - 持仓上限
$$

4. 淘汰排名末尾的 N 个对象。
5. 若被淘汰的是持仓，则生成平仓或强制退出动作。
6. 若被淘汰的是新信号，则拒绝该信号。
7. 最终保留下来的新信号才进入执行。

这不是小补丁，而是从“信号门控”升级为“组合席位竞争”。

---

## 2. 为什么这个版本必须优先做

### 2.1 当前逻辑的产品级缺陷

现有行为本质上是假设“先来先占坑，后来的再优秀也要排队或被拒绝”。

这在低频、低容量、人工主导的系统中还能接受；但在自主交易系统里，这是明显的资本错配：

1. 旧持仓可能已经质量下降，但因为还没触发独立的 EXIT/REDUCE 规则，继续占用席位。
2. 新信号可能质量更高、胜率更优、与当前体制更匹配，却在 Layer 2 被直接拒绝。
3. 系统因此更像“仓位容量守门器”，而不是“资本分配器”。

### 2.2 顶级量化团队的正确视角

机构系统在容量受限时通常不会问“能不能再开一个仓”，而是问：

1. 当前最差的持仓是否仍值得保留？
2. 新信号的边际 alpha 是否高于末位持仓？
3. 替换一笔持仓后，净收益提升能否覆盖交易成本、滑点与税务摩擦？

因此，V10.5.2 的本质不是“多开几个仓”，而是：

> 用统一准入分数与替换成本模型，实时决定谁该留下，谁该让位。

---

## 3. V10.5.2 核心规划

## M1. Capacity-Aware Admission & Replacement Engine

### 目标

把“持仓上限”从硬拒绝规则升级为实时席位竞争引擎。

### 核心能力

#### 1. Unified Candidate Pool

构建统一候选池，包含两类对象：

- 当前持仓标的
- 本轮待处理开仓信号

系统不再只对“新信号之间”排序，而是对“持仓与新信号混排”。

#### 2. Unified Admission Score

引入统一准入分 `admission_score`，用于跨对象比较。建议结构：

$$
admission\_score = alpha\_quality - replacement\_friction - risk\_penalty + regime\_fit
$$

其中：

- 对新信号：主要来自 `SignalQualityFunnel.preview_quality()`、Conviction Score、体制匹配、相关性约束、预交易成本。
- 对当前持仓：主要来自 `PositionScoringService`、近期 alpha 保真度、持仓归因质量、体制适配度、占用流动性、止盈止损距离、持有衰减。

要求：

1. 信号分和持仓分必须被归一到同一量纲，不能再各算各的。
2. 分数必须可解释，能拆出构成项。
3. 分数必须审计落库，供事后复盘比较“为什么留下 A 而淘汰 B”。

#### 3. Overflow 淘汰算法

当候选池总数超过 `MAX_CONCURRENT_POSITIONS` 时：

$$
overflow = candidate\_pool\_size - max\_positions
$$

按 `admission_score` 从高到低排序，淘汰末尾 `overflow` 个对象。

规则如下：

1. 若对象类型为 `POSITION`，则生成 `EXIT` 或 `FORCE_EXIT` 候选动作。
2. 若对象类型为 `SIGNAL`，则标记为 `REJECTED_BY_CAPACITY_REPLACEMENT`。
3. 仅保留最终排进前 `max_positions` 的对象进入下一步交易链路。

#### 4. 替换保护带

真实交易里，不能因为新信号高 0.1 分就频繁替换持仓。必须加入保护带：

- `MIN_REPLACEMENT_EDGE_BPS`：只有当新信号相对末位持仓的优势超过阈值才允许替换。
- `MAX_REPLACEMENTS_PER_CYCLE`：单轮最多替换 K 个席位，避免组合翻仓过快。
- `MIN_HOLD_MINUTES_BEFORE_REPLACEMENT`：持仓建立后短时间内不允许被普通新信号挤出，避免抖动。
- `REPLACEMENT_COOLDOWN_MINUTES`：同一标的被替换出后，短期内不允许再次入选。

#### 5. 执行顺序控制

替换执行必须是原子化策略，而不是“先开后平”或“只平不补”：

1. 先确定最终保留名单。
2. 对需淘汰的持仓生成关闭动作。
3. 对保留的新信号排入执行。
4. 执行层按“先释放风险预算，再开新仓”顺序推进，避免临时超仓。

### 交付结果

- 系统在满仓时不再直接拒绝高质量新信号。
- 持仓与新信号第一次进入同一竞争序列。
- 组合席位分配从“先占先得”升级为“质量优先”。

---

## M2. Position Decay & Incumbent Quality Governance

### 目标

让持仓不是“进来了就默认保留”，而是持续参与席位竞争。

### 功能清单

#### 1. Incumbent Decay Model

对持仓引入“占位衰减”概念。持仓分数不再只看静态评分，还要看：

- 持有后 alpha 是否衰减
- 当前体制是否仍匹配建仓逻辑
- 已实现/未实现收益是否支持继续持有
- 若继续占用席位，其机会成本有多高

#### 2. Replacement Friction Penalty

被替换的持仓若退出成本很高，应降低替换概率：

- 税费 / 滑点 / spread / lot size 成本
- 执行完成风险
- 当前持仓是否处于盈利围栏、事件窗口或流动性较差时段

#### 3. Hold vs Replace 解释层

前端与审计日志必须能明确回答：

- 为什么这个旧持仓被保留
- 为什么另一个持仓被替换
- 为什么某个新信号虽然质量不错但仍未入选

这对于 FULL 模式的可解释性非常关键。

---

## M3. Capacity Simulation & What-If Console

### 目标

让 PM、研究员和交易员在真正放量前，看到替换机制会如何改变组合。

### 功能清单

#### 1. What-If Replacement Preview

在执行前输出模拟结果：

- 当前持仓列表
- 本轮信号列表
- 统一排序结果
- 被淘汰对象
- 保留对象
- 预计释放/占用的风险预算
- 预计换手成本

#### 2. Replacement Attribution

新增替换归因报表：

- 替换后 1d / 5d / 20d 超额收益
- 被淘汰持仓后续表现
- 被拒绝信号后续表现
- replacement win rate
- false replace rate
- missed replacement opportunity

#### 3. Shadow Replacement Book

对“本应替换但因保护带未替换”的情况建立影子账本，验证保护带是否过宽。

---

## M4. Execution Coordination for Seat Rotation

### 目标

把席位替换从“评分逻辑”真正落到“执行编排”。

### 功能清单

#### 1. Rotation Orchestrator

新增席位轮换编排器，负责协调：

- 平仓候选排序
- 释放资金与风险预算
- 新仓进场顺序
- 同标的冲突消解

#### 2. Atomic Capacity Cycle

一次决策周期内，容量替换应视为同一个事务语义：

- 输入：当前持仓 + 新信号 + 上限
- 输出：退出清单 + 拒绝清单 + 执行清单

不得再出现“先因满仓拒绝新信号，随后又异步发现某些旧仓该出”的分裂体验。

#### 3. Failure Rollback Policy

若退出单失败、部分成交、券商拒单、或市场流动性不足：

- 新开仓自动延后
- 保持组合不超上限
- 标记该轮为 `PARTIAL_ROTATION`
- 后续由重试队列接管

---

## M5. Observability & Governance

### 目标

把“席位竞争”纳入系统治理，不让它成为新的黑箱。

### 功能清单

#### 1. Capacity Decision Audit Log

新增容量决策日志，记录：

- 当前持仓数 / 上限 / 新信号数 / overflow
- 每个候选对象的 admission_score
- 淘汰原因
- 是否因保护带未替换
- 最终执行结果

#### 2. Capacity Dashboard

新增监控指标：

- seat_utilization
- replacement_attempts
- replacement_success_rate
- capacity_rejections_after_comparison
- average_replacement_edge
- turnover_added_by_replacement

#### 3. Governance Rules

新增产品级治理开关：

- `CAPACITY_REPLACEMENT_ENABLED`
- `CAPACITY_REPLACEMENT_DRY_RUN`
- `CAPACITY_REPLACEMENT_MAX_PER_CYCLE`
- `CAPACITY_REPLACEMENT_MIN_EDGE`
- `CAPACITY_REPLACEMENT_REQUIRE_NET_BENEFIT`

支持先以 dry-run 方式只观测、不执行，再逐步放开到实盘。

---

## 4. 关键产品方案细化

### 4.1 用户已知需求的正式产品化定义

用户提出的需求可以被正式定义为：

> 当持仓标的总数达到或超过持仓上限时，不直接拒绝新信号，而是将“当前持仓 + 新信号”组成统一候选池，按统一质量排序，淘汰末位 N 个对象；若末位对象是持仓则执行平仓，若是信号则拒绝，最终仅让保留下来的信号执行交易。

这是 V10.5.2 的 P0 必做项。

### 4.2 建议的统一评分框架

建议将候选对象统一为如下抽象：

```text
Candidate {
  candidate_type: POSITION | SIGNAL
  symbol
  side
  regime
  quality_score
  friction_penalty
  risk_penalty
  regime_fit
  admission_score
  explain
}
```

其中：

- `POSITION.quality_score` 可复用 `PositionScoringService` 的 overall score，并结合持仓衰减、归因、体制适配做二次修正。
- `SIGNAL.quality_score` 可复用 `SignalQualityFunnel.preview_quality()` 与 conviction score。

### 4.3 必须避免的三种错误实现

#### 错误一：只比较 signal 分，不比较 position 分

这会导致系统仍无法真正做席位替换，只是让新信号之间重新排队。

#### 错误二：只在持仓超限后再异步减仓

这会导致准入与退出解耦，依然会发生“好信号被拒，差持仓晚一点才被卖”的错配。

#### 错误三：没有替换摩擦成本和保护带

这会导致系统过度交易，席位轮换变成 churn engine，而不是 alpha allocator。

---

## 5. 预期涉及的系统改造面

### 后端核心链路

- `SignalQualityFunnel`：Layer 2 从“满仓即拒绝”升级为“进入席位竞争流程”。
- `AutonomousEngine`：在信号排序后、RiskGate 前引入 unified capacity decision。
- `PositionRebalanceMonitor`：从“超限后异步降载”升级为“席位竞争的数据供应方与兜底守卫”。
- `PositionScoringService`：补齐可与 signal quality 对齐的统一准入评分接口。
- `RiskGateService`：支持替换路径的风险预算预占与释放顺序校验。

### 数据与审计

- 新增容量决策日志表
- 新增候选评分快照
- 新增替换归因与影子账本

### 前端与运维

- Autonomy / Order Book / Portfolio 页增加“席位竞争结果”可视化
- System Monitor 增加 capacity rotation 健康状态、dry-run 结果和替换命中率

---

## 6. 北极星指标与验收标准

### 6.1 北极星指标

| 指标 | 定义 | V10.5.2 目标 |
|------|------|-------------|
| Capacity Admission Accuracy | 被替换保留的对象在未来 5d 表现优于被淘汰对象的比例 | ≥ 60% |
| False Rejection Rate | 被拒新信号未来表现显著优于保留组合末位对象的比例 | 较 V10.5.1 下降 30% |
| Replacement Net Benefit | 替换后收益扣除交易成本后的净提升 | 为正 |
| Seat Turnover Discipline | 单日由替换逻辑额外引入的换手 | 在预算内 |
| Full-Audit Coverage | 每次满仓准入决策可回放比例 | 100% |

### 6.2 P0 验收标准

- [ ] 当 `current_positions + incoming_signals > max_positions` 时，系统不再直接因满仓拒绝全部新信号。
- [ ] 系统可对“当前持仓 + 新信号”生成统一排序结果与 overflow 淘汰清单。
- [ ] 被淘汰持仓自动进入 `EXIT/FORCE_EXIT` 编排；被淘汰信号进入容量拒绝状态。
- [ ] 审计日志可展示每个对象的 `admission_score`、淘汰原因和保护带结果。
- [ ] 新旧对象比较支持 dry-run 模式，可先只观测不执行。

### 6.3 P1 验收标准

- [ ] 保护带、冷却期、每轮替换上限可配置。
- [ ] 前端可展示替换前后组合变化、风险预算释放与新增换手。
- [ ] 有 replacement attribution 报表，能回答替换机制是否真的提高净收益。

---

## 7. 版本节奏建议

### Stage A: Dry Run

- 只计算统一排序，不执行替换
- 连续观察 2 周
- 重点看 false reject / false replace / shadow replacement 指标

### Stage B: Paper Trading Activation

- 在 Paper 环境启用真实替换执行
- 检查原子执行、失败回滚、部分成交与队列顺序

### Stage C: Live Controlled Rollout

- 先仅允许每轮替换 1 个席位
- 再放开到 2~3 个席位
- 最后才开放完整席位轮换

---

## 8. 最终判断

如果说 V10.5.1 解决的是“这个系统能否成为机构级研究与交易操作系统”，那么 V10.5.2 解决的是另一个更尖锐的问题：

> 当资本、风险预算和持仓席位都稀缺时，系统是否真的会把资源分配给当下最值得拥有它们的对象。

这一步做完，平台才真正从“高质量信号筛选器”升级为“组合资本配置器”。

而从产品价值上看，这比再增加几个分析页面或再多接几个策略，更接近华尔街顶级量化平台的核心竞争力。