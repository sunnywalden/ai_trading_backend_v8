# LLM-Native Quant OS 设计提案

> 状态：提案 / 讨论稿（尚未实现）  
> 适用范围：后端认知架构、交易主链演进、自治研究与自诊断体系  
> 更新时间：2026-03-15

---

## 1. 设计动机

当前平台已经具备较强的交易控制平面能力：

- `AutonomousEngine.run_decision_cycle()` 统一自动执行主链
- `SignalQualityFunnel`、`CapacityArbiterService`、`RiskGateService`、`Circuit Breaker` 构成分层治理边界
- `MetaStateSnapshotService`、`ImprovementCandidateService`、`DecisionPostMortemService`、`CopilotService` 提供观察、解释与局部 AI 增强能力

但从架构本质看，当前系统仍然是：

> **控制平面主导的量化交易平台，LLM 作为局部分析器 / 解释器 / 辅助决策器存在。**

它还不是一个真正的 **LLM-native Quant Platform**，原因在于：

1. **交易主链仍由规则/状态机驱动**，而非由持续存在的认知内核驱动。
2. **LLM 调用仍以单次函数式调用为主**，缺少长期记忆、目标追踪、自我解释与持续反思。
3. **多智能体协作尚未成为生产主脑**，更多停留在旁路能力或专题能力层。
4. **自我优化更多体现为参数级优化**，而不是“提出研究问题 → 形成假设 → 执行实验 → 选择进化方向”的自治研究循环。
5. **故障定位仍偏运维监控式**，尚未形成 AI 驱动的根因理解与修复建议闭环。

本提案的目标，是在不破坏当前风险边界与执行纪律的前提下，将平台逐步演进为：

> **以大模型为认知中枢、以确定性风险内核为生存边界的自治量化操作系统。**

---

## 2. 目标定义

### 2.1 一句话定位

**LLM-Native Quant OS**：一个以大模型为认知内核，能够进行自我建模、世界建模、目标规划、反思纠错、自主研究和自诊断的量化交易操作系统。

### 2.2 核心原则

1. **LLM 负责认知，不直接裸奔执行。**
2. **规则层不消失，而是降级为生存边界层。**
3. **交易只是认知循环的一种输出，不是系统唯一目标。**
4. **平台必须具备连续记忆，而不是每轮重新“失忆开机”。**
5. **反思、自诊断、自主研究必须进入主循环，而不是盘后附加功能。**

---

## 3. 当前平台与目标平台的差距

| 维度 | 当前平台 | 目标平台 |
| ------ | ---------- | ---------- |
| 主脑形态 | `AutonomousEngine` + 控制平面 | `Cognitive Kernel` + 认知循环 |
| LLM 角色 | 局部分析、摘要、单次决策 | 持续感知、规划、反思、研究 |
| 驱动方式 | `pending signals -> evaluate -> execute` | `goal -> perceive -> deliberate -> plan -> act -> reflect` |
| 记忆 | 日志/审计/快照为主 | 短期工作记忆 + 中期情境记忆 + 长期原则记忆 |
| 自我优化 | 参数/权重/候选改进 | 自主提出研究问题并做实验治理 |
| 故障定位 | 健康检查 + 指标 + watchdog | 根因分析 + 修复建议 + 验证计划 |
| 多智能体 | 专题协作/旁路能力 | 主认知链 deliberation layer |

---

## 4. 目标架构总览

```mermaid
flowchart TB
    subgraph Interface[交互层]
        FE[Frontend / Workbench / Copilot]
        API[FastAPI Routers]
    end

    subgraph Cognitive[认知自治层]
        CK[Cognitive Kernel]
        SM[Self Model]
        WM[World Model]
        GM[Goal Manager]
        DL[Deliberation Layer]
        RF[Reflection Engine]
        SD[Self-Diagnostics]
        RL[Research Loop]
        MEM[Memory System]
    end

    subgraph Safety[确定性边界层]
        RG[Risk Gate]
        CA[Capacity Arbiter]
        GOV[Governance / Flags]
        EP[Execution Policy]
        AUDIT[Audit / Truth Source]
    end

    subgraph Runtime[执行与运行层]
        AE[Execution Coordinator]
        OE[Order Executor]
        PM[Position Monitor]
        PTP[Post-Trade Pipeline]
        JOBS[Scheduler Jobs]
    end

    Interface --> API --> CK
    CK --> SM
    CK --> WM
    CK --> GM
    CK --> DL
    CK --> RF
    CK --> SD
    CK --> RL
    CK <--> MEM

    CK --> Safety
    Safety --> AE
    AE --> OE
    Runtime --> MEM
    JOBS --> CK
    JOBS --> Runtime
    OE --> AUDIT
    PM --> RF
    PTP --> RL
```

### 4.1 架构解释

- **认知自治层**：负责“理解、规划、解释、研究、反思”。
- **确定性边界层**：负责“什么不能做错”。
- **执行与运行层**：负责“把批准后的行动真正落地”。

当前平台最强的是第二层与第三层；未来演进重点应集中在第一层。

---

## 5. 六大原生能力

### 5.1 Self Model（自我模型）

系统需要维护自身状态，而不仅是账户状态。

应回答：

- 当前模型在哪些 regime 下最易误判？
- 当前主要收益依赖哪些因子/叙事？
- 当前是“过于保守”还是“过于激进”？
- 最近推理质量是否退化？
- 哪些 hard gate 长期阻塞资金周转？

建议输出对象：

- `self_state_snapshot`
- `decision_style_profile`
- `confidence_drift_profile`
- `failure_mode_clusters`

### 5.2 World Model（世界模型）

系统不应只读取指标，而要持续维护市场世界解释。

应覆盖：

- regime 及其可信度
- 主叙事与反叙事
- 风险簇与相关性团簇
- 事件-资产-组合的传播路径
- 价格、资金流、新闻、宏观之间的因果假设

建议输出对象：

- `market_world_state`
- `narrative_graph`
- `risk_cluster_map`
- `event_impact_hypotheses`

### 5.3 Goal Manager（目标管理）

系统需要显式回答“今天的最优行动类型是什么”，而不是只对 signal 被动响应。

目标示例：

- 提高资本效率
- 降低组合脆弱性
- 观察某叙事是否形成趋势
- 保护高价值头寸
- 进入研究模式而非交易模式

### 5.4 Reflection Engine（反思引擎）

反思需要进入主循环，覆盖：

- **事前反思**：为什么这笔交易可能错？
- **事中反思**：当前行动是否偏离 thesis？
- **事后反思**：失败来自市场、执行、认知还是治理门？
- **元反思**：最近一周的判断风格是否发生偏移？

### 5.5 Self-Diagnostics（自诊断）

自诊断能力不只是“服务挂了没”，而是“为什么系统没做出应有动作”。

需要回答：

- 为什么今天零交易？
- 为什么高置信度信号持续被拒？
- 为什么执行质量恶化？
- 为什么校准因子持续向 0.5 收敛？
- 为什么某类研究方向持续无效？

输出目标：

- `root_cause_report`
- `evidence_chain`
- `repair_recommendations`
- `verification_plan`

### 5.6 Research Loop（自治研究循环）

系统必须能把“自我优化”升级为“自我研究”。

标准闭环：

1. 发现异常/机会
2. 提出研究问题
3. 形成假设
4. 设计 shadow / paper / backtest 实验
5. 比较结果
6. 提交升级/回滚建议

这要求研究循环与治理放量严格绑定，而不是直接改 live 行为。

---

## 6. 认知循环（Cognitive Cycle）

目标系统的主循环应从当前：

```text
pending signals -> ai decide -> risk gate -> execute
```

升级为：

```text
observe -> update self/world model -> set goals -> deliberate -> generate action plan ->
deterministic validation -> execute -> reflect -> update memory
```

### 6.1 认知循环时序

```mermaid
sequenceDiagram
    participant Jobs as Scheduler / Event Triggers
    participant CK as Cognitive Kernel
    participant MEM as Memory System
    participant DL as Deliberation Layer
    participant SAFE as Risk/Governance Kernel
    participant EXEC as Execution Coordinator
    participant POST as Reflection + Research Loop

    Jobs->>CK: trigger cognitive cycle
    CK->>MEM: load recent self/world/task memory
    CK->>CK: update self model + world model
    CK->>CK: prioritize goals
    CK->>DL: request deliberation
    DL-->>CK: action candidates + objections + rationale
    CK->>SAFE: validate plan
    SAFE-->>CK: accepted / rejected / degraded
    CK->>EXEC: submit approved actions
    EXEC-->>POST: execution outcome + audit + anomalies
    POST->>MEM: persist lessons / failures / hypotheses
```

---

## 7. 分层落地建议（映射当前仓库）

### 7.1 新增认知中枢目录

建议在 `app/services/` 下新增一组认知服务：

```text
app/services/
  cognitive_kernel.py
  self_model_service.py
  world_model_service.py
  goal_manager_service.py
  reflection_service.py
  self_diagnostics_service.py
  memory_service.py
  research_governor_service.py
```

### 7.2 现有服务的角色重定位

| 当前服务 | 当前角色 | 未来角色 |
| ---------- | ---------- | ---------- |
| `AutonomousEngine` | 自动执行主脑 | 降级为 `Execution Coordinator` |
| `MultiAgentOrchestrator` | 专题多智能体 | 升级为 `Deliberation Layer` 核心实现 |
| `CopilotService` | 对话接口 | 认知层的人工交互面板 |
| `MetaStateSnapshotService` | 自知画像快照 | 并入 `SelfModelService` |
| `DecisionPostMortemService` | 盘后剖析 | 并入 `ReflectionService` |
| `ImprovementCandidateService` | 改进候选生成 | 并入 `ResearchGovernorService` |

### 7.3 主链入口迁移建议

现状：

- `run_autonomous_decision_cycle` → `AutonomousEngine.run_decision_cycle()`

目标：

- `run_cognitive_cycle` → `CognitiveKernel.run_cycle()`
- `CognitiveKernel` 生成 `ActionPlan`
- `ExecutionCoordinator` 负责调用 `RiskGate` / `CapacityArbiter` / `OrderExecutor`

---

## 8. Memory System 设计

### 8.1 三层记忆

#### A. Working Memory（工作记忆）

保存本交易日/当前周期的重要上下文：

- 当前 regime
- 当前叙事
- 当前关注标的与关注风险
- 当前待决议任务

#### B. Episodic Memory（情境记忆）

保存近期发生的关键经验：

- 某类信号连续失败的上下文
- 某次执行异常的全过程
- 某个风控门长期阻塞的证据链

#### C. Semantic Memory（原则记忆）

保存平台长期稳定的经验规则：

- 哪些 regime 下应收缩激进度
- 哪些叙事经常导致虚假突破
- 哪些实验曾被证明无效

### 8.2 建议数据对象

- `cognitive_memory_entries`
- `thesis_journal`
- `reflection_episodes`
- `research_hypotheses`
- `system_principles`

---

## 9. 多智能体主链化建议

不建议把当前多智能体直接接到下单链，而应先形成 **Deliberation Layer**。

建议角色：

- `MarketSenseAgent`：市场叙事、regime、热点与拥挤度理解
- `PortfolioAgent`：组合层机会成本、风险预算、资本效率
- `RiskCriticAgent`：强制反驳与极端场景挑战
- `ExecutionAgent`：执行窗口、算法、成交风险建议
- `ReflectionAgent`：从历史 episode 中提取“别再犯什么错”
- `SREAgent`：定位数据/任务/模型/券商链路异常
- `GovernorAgent`：综合裁决并生成结构化 `ActionPlan`

### 9.1 ActionPlan 建议结构

```json
{
  "cycle_id": "uuid",
  "goal": "improve-capital-efficiency",
  "world_state_ref": "snapshot-id",
  "actions": [
    {
      "type": "TRADE_ENTRY",
      "symbol": "NVDA",
      "reason": "trend-strength + narrative confirmation + portfolio fit",
      "confidence": 0.78,
      "risk_thesis": "acceptable under current beta budget"
    }
  ],
  "objections": [
    "crowding elevated",
    "earnings event proximity"
  ],
  "fallbacks": [
    "switch to monitor-only if execution slippage > threshold"
  ]
}
```

---

## 10. 确定性边界层保持不变的部分

以下能力不应被“LLM 原生化”替代，而应保留为确定性内核：

- `RiskGateService`
- `CapacityArbiterService`
- `ExecutionPolicyService`
- execution intent 幂等保护
- circuit breaker
- 审计真源与状态迁移真源
- rollout phases 与 feature flags

原则：

> **让模型负责更聪明，但不让模型负责更鲁莽。**

---

## 11. 分阶段演进路线

### Phase 1：认知内核成型（低风险）

目标：引入 `CognitiveKernel`，但不改变 live 执行链路。

交付：

- 新增 `CognitiveKernel.run_cycle()`
- 汇总 `SelfModel` / `WorldModel` / `GoalManager`
- 输出 `ActionPlan`，仅用于 shadow/observe
- 前端 `/autonomy` 新增“认知状态”工作台

### Phase 2：多智能体 deliberation 接主链前置（中风险）

目标：将 `MultiAgentOrchestrator` 重构为 deliberation layer，但仍不直接下单。

交付：

- 输出 objections / alternatives / rationale
- 与 `ActionPlan` 绑定
- 对主链执行结果进行计划-结果偏差比对

### Phase 3：执行协调器改造（中风险）

目标：把 `AutonomousEngine` 从“思考 + 执行”拆成“执行协调器”。

交付：

- `ExecutionCoordinator` 接收 `ActionPlan`
- 原 `_ai_decide()` 退役或收缩为 fallback mechanism
- `RiskGate` / `CapacityArbiter` / audit 流程保持不变

### Phase 4：反思 / 自诊断 / 自主研究闭环（中高风险）

目标：把 `post-mortem`、`improvement candidate`、`meta-state` 统一成主循环反馈层。

交付：

- `ReflectionService`
- `SelfDiagnosticsService`
- `ResearchGovernorService`
- shadow/paper 实验治理流水线

### Phase 5：有限真实接管（高风险）

目标：只在严格 feature flag + observe/shadow/semi 纪律下，让认知内核对真实执行产生有限影响。

前提：

- replay 与审计可回放
- 认知计划与最终执行差异可比较
- 反思质量稳定
- 故障诊断有明确误报控制

---

## 12. API 与工作台建议

### 12.1 建议新增 API

```text
GET  /api/v1/cognitive/state
GET  /api/v1/cognitive/world-model
GET  /api/v1/cognitive/self-model
GET  /api/v1/cognitive/goals
GET  /api/v1/cognitive/action-plans
GET  /api/v1/cognitive/reflections
GET  /api/v1/cognitive/diagnostics
GET  /api/v1/cognitive/research-hypotheses
POST /api/v1/cognitive/run-cycle
```

### 12.2 前端建议工作台

建议在 `/autonomy` 之上增加新的认知视图：

- 当前目标与目标切换原因
- 当前市场叙事图谱
- 系统自我状态画像
- 当前 objections / alternatives / chosen plan
- 最近反思与根因诊断
- 当前研究假设队列

---

## 13. 风险与边界

### 13.1 最大风险

1. **把 LLM-native 误解为“LLM 直接替代所有确定性规则”**
2. **引入复杂 agent 但没有审计真源，导致更黑盒**
3. **没有记忆治理，导致系统持续“自我污染”**
4. **研究循环直接影响 live 行为，绕过 rollout discipline**

### 13.2 应对原则

- 所有认知输出先进入 `shadow` 观测
- 所有研究结论先进入 `paper` / `replay`
- 所有行动提案必须经过 deterministic validation
- 所有自诊断结论必须附 evidence chain

---

## 14. 结论

当前平台并非“大模型原生量化平台”，但它已经具备良好的：

- 风险边界层
- 执行内核
- 审计与治理框架
- 工作台与观测基础

因此最合理的路径不是推倒重来，而是：

> **保留当前确定性控制面作为生存边界，新增以 `CognitiveKernel` 为核心的认知自治层，逐步把平台从“规则主导 + LLM 辅助”演进为“LLM 认知主导 + 风险内核托底”的 Quant OS。**

这也是当前仓库在工程上最现实、最安全、也最符合你目标愿景的方向。

---

## 15. 专家评审团多视角可行性评估

> 评审时间：2026-03-15  
> 评审视角：华尔街顶尖量化专家 / 硅谷顶尖 LLM 技术专家 / 硅谷顶尖 LLM 应用产品经理 / 华尔街顶尖交易员

---

### 15.1 华尔街量化专家视角：条件可行，但需先回答"LLM reasoning 能否产生 α"

**核心判断：这是一个信念命题，必须拆解"可行"的前提。**

目前没有任何公开的严格 RCT 级别证据证明，LLM 生成的市场叙事（narrative reasoning）能持续跑赢传统因子模型。本方案对此保持沉默是一个根本性缺口。

合理的假设应该是：

> LLM 的价值不在于"更聪明地预测价格"，而在于**更有效地综合异构信息**（新闻、财报语义、期权 flow、宏观叙事之间的关联）。这种信息融合能力是传统因子框架的结构性盲点，LLM 在此处有差异化优势。

**各模块量化合理性评分（1–10）：**

| 模块 | 评分 | 主要评语 |
| ------ | ---- | -------- |
| World Model（世界建模） | 7 | 方向正确，但缺少"如何验证 World Model 有效性"的机制 |
| Self Model（自我建模） | 8 | 目前最稀缺的能力，方向准确 |
| Research Loop（自治研究） | 5 | 过于乐观；研究循环容易产生叙事过拟合（narrative overfitting） |
| Reflection Engine（反思） | 8 | 高价值，postmortem → 记忆 → 策略调整的链路在机构里确有 α |
| Goal Manager（目标管理） | 6 | 概念正确，但缺少显式的目标-仓位映射框架（如 Kelly / 风险预算树） |

#### 最大风险（量化视角）：叙事自我强化（Narrative Overfitting）

系统自己生成世界观、自己验证、自己归因，极容易形成自洽但错误的信念闭环。传统因子模型至少有价格作为外部 Ground Truth；认知内核的 Ground Truth 需要被显式定义。

---

### 15.2 硅谷 LLM 技术专家视角：技术上刚进入"可以认真做"的窗口

**关键技术成熟节点：**

- 2024 Q3：Tool use / function calling 可靠性达到生产级
- 2024 Q4：长上下文（128k+）可用于完整的日内记忆上下文
- 2025 Q1：Reasoning models（o3、deepseek-reasoner）在多步推理上显著优于 chat models
- 2025 Q4：Structured output（JSON mode）可靠性达到 99%+

**各技术需求可行性评估：**

| 技术需求 | 可行性 | 主要限制 |
| -------- | ------ | -------- |
| Cognitive Kernel + ActionPlan JSON 输出 | 高 | 需要严格 prompt 工程，reasoner 类模型优先 |
| 三层记忆系统（Working / Episodic / Semantic） | 中高 | Working Memory 可上下文注入；Episodic 需 RAG；Semantic 需向量数据库 |
| 多智能体并发 deliberation | 中 | 7 个 agent 串行 = 30–60 秒，并行可降至 10–15 秒；日线策略可接受 |
| 实时世界模型更新 | 中低 | 真正"实时"成本极高；建议 15 分钟批量更新 |
| 研究循环自主执行代码 | 低–中 | Code Interpreter 类 agent 已成熟，但金融数据沙箱安全隔离需额外工程 |

**方案中最严重的三项技术缺失：**

1. **幻觉检测层（Hallucination Guard）缺失**：LLM 对金融数字的幻觉率是通用任务的 3–5 倍。`ActionPlan` 中的 `confidence: 0.78` 可能是完全杜撰的，方案没有任何机制检测这一点。

2. **模型版本管理缺失**：Episodic Memory 是由特定模型的推理风格生成的。当 gpt-4o 被 o4 替换时，旧记忆的语义解读方式会发生漂移，需要有显式的模型版本标记与记忆重校准机制。

3. **向量数据库选型完全缺失**：Episodic Memory 的检索依赖语义搜索（RAG），这是基础设施级决策，方案文档目前跳过了这一选型。

---

### 15.3 硅谷 LLM 产品经理视角：产品逻辑自洽，但缺少可衡量的成功定义

**方案的产品成熟度问题：KPI 完全缺失。**

没有以下问题的答案，方案无法指导产品迭代：

- Cognitive Kernel 的"决策质量"如何衡量？（不能只看 P&L，α 与系统决策质量是有噪声相关的）
- World Model 的准确度如何评估？（叙事无法用精确率/召回率衡量）
- ReflectionEngine 的反思是否真的影响了后续决策？（需要 A/B 测试框架）

**最大产品风险：**

> 系统的认知过程对用户（交易员自己）不透明，导致"我不知道它在想什么"的信任断裂。当系统做出错误决策，用户无法归因、无法改正、无法建立信心。**Explainability 不是工作台的附加功能，它是整个产品的核心价值主张。**

---

### 15.4 华尔街交易员视角：架构对日线+时间框架合理，对盘中是灾难

**核心问题：时间尺度与认知延迟不匹配。**

认知循环中的多智能体 deliberation 即使并行调用，最快也需要 10–20 秒。

| 策略类型 | 认知决策延迟 | 适用性 |
| -------- | ----------- | ------ |
| 日内高频（秒级） | 不可接受 | ❌ 必须保留纯规则引擎 |
| 日内趋势跟踪（分钟级） | 勉强 | ⚠️ 需要异步预计算 |
| 日线摆动交易 | 可接受 | ✅ 这是方案的主战场 |
| 多日组合管理 | 非常合适 | ✅ 认知价值最高 |

当前平台的信号生成是日线级的，这个时间框架下 LLM 认知架构完全合理。

**方案中严重缺失的交易实务维度：**

1. **仓位规模化（Position Sizing）**：`ActionPlan` 里的 `confidence: 0.78` 如何映射到具体仓位大小？缺少 Kelly 公式、风险预算或因子暴露约束的显式框架。
2. **市场冲击成本（Market Impact）**：设计中完全没有，即使对小账户也应至少有占比估算。
3. **流动性感知**：Deliberation Layer 讨论"进入某标的"，但没有"以多快速度能出来"的流动性约束。

---

## 16. 月度成本估算

### 16.1 LLM API 成本

**假设：每日 15 个认知循环（美股盘前 / 盘中 / 盘后），每循环涉及以下调用（以 DeepSeek 为主力模型）：**

| 调用类型 | 模型选择 | token 消耗（估算） | 单价 | 每循环成本 |
| -------- | -------- | ------------------ | ---- | ---------- |
| WorldModel 更新 | deepseek-chat | ~8k in / 2k out | $0.27/M | ~$0.003 |
| 7 Agents deliberation（并行） | deepseek-reasoner | ~5k in / 1k out × 7 | $0.55/M in | ~$0.02 |
| GovernorAgent ActionPlan | deepseek-reasoner | ~15k in / 3k out | $1.1/M in | ~$0.018 |
| Reflection post-trade（每笔） | deepseek-chat | ~4k in / 1k out | $0.27/M | ~$0.001/笔 |
| SelfModel 每日快照 | deepseek-reasoner | ~10k in / 2k out | $0.55/M | ~$0.007/次 |
| ResearchLoop（2–3 次/日） | deepseek-reasoner | ~20k in / 5k out | $2.19/M out | ~$0.015/次 |

月度 LLM API 成本合计（DeepSeek 主力路线）约 **$25–50/月**。

如关键决策切换 GPT-4o / o3 作主力：**约 $150–400/月**

### 16.2 Google Cloud 基础设施成本

| 组件 | 规格建议 | 月成本（估算） |
| ---- | -------- | -------------- |
| API Server（FastAPI + APScheduler） | e2-standard-4（4vCPU / 16GB） | ~$130 |
| MySQL 数据库 | Cloud SQL db-n1-standard-2 | ~$120 |
| Redis（Working Memory + Cache） | Memorystore 1GB Basic | ~$35 |
| 向量数据库（Episodic Memory） | Qdrant on e2-small 或 Weaviate Cloud Free | $0–$25 |
| 存储（DB + 日志 + 回测数据） | 200GB SSD | ~$34 |
| 负载均衡 + 网络出口 | 标准配置 | ~$20 |
| **合计** | | **~$340–365/月** |

> 可优化：使用 Spot / Preemptible 实例可降低 API Server 成本约 60%，总基础设施可降至 ~$280/月。

### 16.3 券商 API 成本（Tiger Brokers）

Tiger API 对个人开发者免费，成本来自交易佣金：

| 品种 | 费率 | 月成本估算（20–30 笔/月） |
| ---- | ---- | ------------------------ |
| 美股 | $0.005/股（最低 $1/笔） | $20–$50 |
| 港股 | ~0.03–0.05%/笔 | $10–$30 |
| 期权 | ~$0.65/合约 | 视频率而定 |
| **合计** | | **~$30–$80/月** |

### 16.4 总月度成本汇总

| 类别 | 保守估算 | 经过优化 |
| ---- | -------- | -------- |
| LLM API（DeepSeek 主力） | $50 | $25 |
| LLM API（GPT-4o/o3 精选） | +$100 | +$50 |
| Google Cloud 基础设施 | $365 | $280（Spot 实例） |
| 向量数据库 | $25 | $0（自建 Qdrant） |
| Tiger 佣金 | $80 | $30 |
| **总计** | **~$620/月** | **~$385/月** |

**结论：对个人量化交易者，$400–650/月的月运营成本非常可控。LLM API 成本可通过模型选择压缩至整体成本的 5–15%。**

---

## 17. 改造路径评估：增量演进 vs 从零重建

### 17.1 评审结论：强烈建议增量演进，对 `AutonomousEngine` 做一次计划内战略拆分

**支持增量改造的核心资产：**

| 现有资产 | 价值定性 | 从零重建成本估算 |
| -------- | -------- | ---------------- |
| RiskGate / CapacityArbiter / ExecutionPolicy | 生产验证的确定性安全边界 | 6–12 个月 |
| Tiger Broker 集成（美股/港股/期权） | 处理了大量 edge case | 2–4 个月 |
| Position lifecycle 管理（聚合根 + FSM） | V10.3.2 以来的深度工程积累 | 3–6 个月 |
| Signal pipeline（quality funnel + audit） | V10.5.4 以来的信号治理体系 | 2–3 个月 |
| APScheduler 任务编排 | 成熟可靠 | 1 个月 |
| 前端工作台（WorkbenchShell 体系） | V11.1.1 已建立良好基础 | 3–4 个月 |

重建以上内容约需 **12–24 个月工程时间**，期间实盘交易中断。

### 17.2 当前最大的改造阻力

`AutonomousEngine` 是一个约 2000 行的单体服务，同时承担"认知推理"与"执行协调"两个职责。Phase 3 的主链迁移时，这个类将是主要工程痛点。

**建议：不重建整个项目，但对 `AutonomousEngine` 做一次规划内的战略性拆分：**

- 提取"决策推理"部分 → `CognitiveKernel`
- 保留"执行协调"部分降级 → `ExecutionCoordinator`
- 这是增量改造，而非重写

### 17.3 最终建议

```text
推荐路径 = 在当前仓库增量演进 + AutonomousEngine 一次计划内战略拆分
不建议   = 从零起新项目（完全放弃现有生产验证的风控资产）
```

---

## 18. 方案文档缺口分析与设计优化建议

### 18.1 结构性缺失（G1–G5）

#### G1：缺少 α 归因框架（Alpha Attribution Stack）

方案定义了 World Model 和 Self Model，但没有定义"是什么在赚钱"的显式测量机制。如果不知道当前 α 来源，自我优化就是盲目的。需要一个 `AlphaTruthStack`，将每笔交易最终归因到：信息优势 / 执行优势 / 运气 之中的哪一个。

#### G2：时间尺度分层完全缺失

方案把所有策略放在同一个认知循环频率里。应该有三个时间层：

- **战术层**（每 5–15 分钟）：轻量世界模型刷新 + 持仓风险扫描，不需要 full deliberation
- **操作层**（每小时 / 每日）：完整认知循环 + multi-agent deliberation
- **战略层**（每周）：深度 Self Model 回顾 + Research Loop + 系统原则更新

#### G3：记忆系统缺少遗忘机制与污染防护

文档只描述了"怎么写入记忆"，没有描述"怎么淘汰错误记忆"。金融市场存在 regime change，2022 年熊市习得的"经验"在 2025 年可能有害。需要：

- Episodic memory 的时间衰减权重
- Semantic memory 的"挑战-验证"机制（每条原则都要有被证伪的可能）
- 记忆置信度（belief confidence）字段，而不只是事实记录

#### G4：幻觉防护层（Hallucination Guard）缺失

每个 LLM 输出的数字（confidence score、predicted return、risk estimate）都需要独立的 Ground Truth 对照检查，不能让 LLM 自己估计 `confidence: 0.78` 后直接路由到下单链。

#### G5：Human-in-the-loop Escalation 路径未设计

方案主要描述全自动路径，但以下场景无处理协议：

- 系统对某个决策的 confidence 低于阈值
- 多个 agent 严重分歧（disagreement score 过高）
- 市场进入极端波动（VIX > 35）
- 认知循环连续失败

### 18.2 设计层面优化建议（O1–O4）

#### O1：ActionPlan 结构需要强化

当前 `ActionPlan` 缺少以下关键字段：

```json
{
  "timeframe_sensitivity": "daily-close",
  "position_sizing_model": {
    "method": "risk_parity",
    "target_var_contribution_pct": 0.05
  },
  "invalidation_conditions": [
    "price < support_level by 2%",
    "volume < 0.5x average"
  ],
  "escalate_to_human_if": "agent_disagreement_score > 0.4",
  "memory_relevance_refs": ["episode-2025-11-03", "principle-momentum-in-high-vol"]
}
```

#### O2：World Model 需要"可证伪"的市场假设

不能只有叙事（narrative），必须绑定可测试的预测：

```text
叙事：科技业 AI 资本开支超预期
预测：NVDA/AMD 在下季度财报前有 20% 概率超预期
跟踪：实际财报数据是否与预测一致
```

叙事如果不绑定可验证的预测，Research Loop 就是在做创意写作。

#### O3：Self Model 需要显式分离"认知状态"与"账户状态"

- `AccountState`：资金、持仓、P&L——客观真相，不能由 LLM 生成
- `CognitiveState`：系统的"自我认知"——可以由 LLM 维护，但必须对照 `AccountState` 定期校验

区分这两个状态是防止 LLM 自我欺骗（cognitive dissonance）的基础。

#### O4：`SREAgent` 应移出 Deliberation Layer

`SREAgent`（运维定位）放在交易 deliberation 时间槽内是职责错位。SRE 类能力应该独立成一个并行监控通道，不参与交易决策的 agent 协商，只在异常时触发 escalation。

---

## 19. 超越原方案的前沿演进方向

以下方向不受"修复当前缺陷"限制，是 LLM-Native Quant OS 在理念上的前沿延伸，供战略演进参考。

---

### 19.1 市场参与者 Theory of Mind（对手方建模）

当前 World Model 只建模"市场状态"，不建模"其他参与者行为"。真正有 α 的认知是：

> "动量交易者现在在什么位置？机构是在积累还是在派发？期权做市商的 gamma 敞口会把价格钉在哪里？"

这需要一个 `MarketActorModel`，从 order flow、期权持仓分布、融资余额、ETF 资金流构建隐含的对手方行为假设。这类异构信息融合正是 LLM 的差异化优势所在。

---

### 19.2 反事实引擎（Counterfactual Reasoning Engine）

每次决策后，系统自动生成：

- 如果选了候选方案 B 而非 A，今天结果如何？
- 如果早/晚入场 2 小时，结果会不同吗？
- 导致最终结果的是市场因素还是我的决策质量？

反事实不是为了后悔，而是构建**系统化的决策质量数据集**，用于识别系统性认知偏差（如对小盘股情绪偏乐观），或未来微调系统的决策风格。

---

### 19.3 信念图谱（Belief Graph）替代纯文本 World Model

纯文本 World Model 难以量化、难以追踪矛盾。更强大的方案：

```text
节点：市场实体（资产、因子、事件、参与者）
边：因果关系 + 置信度 + 时效性

示例：
  FED_HAWKISH  --[降低, 置信度 0.8]--> TECH_VALUATION
  USD_STRENGTH --[压制, 置信度 0.7]--> EM_EQUITY_FLOW
  NVDA_EARNINGS_BEAT --[可能触发, 置信度 0.6]--> AI_SECTOR_RERATING
```

LLM 负责从新信息中提取新的节点和边并更新置信度。这让 World Model 从"一篇文章"变成"一个可查询、可推理、可回滚的知识结构"，可用 Neo4j 或内存图结构存储。

---

### 19.4 异步预计算认知（Async Pre-Computed Cognition）

解决 deliberation 延迟问题的优雅方案——不是"需要决策时才运行 agents"，而是**持续预计算**：

- **盘前**：完成当日认知循环，生成 pre-approved action plan 候选池
- **盘中行情触发**：只做轻量的"条件是否满足"检查，而非重新召开 agent 会议
- **行情突变（circuit breaker 触发）**：紧急覆盖循环，限时 5 秒，只召唤 `RiskCriticAgent` + `GovernorAgent`

这样，交易执行延迟从"deliberation 时间"变成"条件检查时间"（毫秒级）。

---

### 19.5 认知漂移监控（Cognitive Drift Monitoring）

LLM 系统的"决策人格"会随时间漂移。需要一个**周期性认知校准器**：

- 每周使用相同的标准化情景测试集（benchmark scenarios）驱动系统
- 记录系统在同样情景下的决策变化趋势
- 检测：是否变得更保守/激进？是否偏好特定板块？是否改变了对风险的态度？

这是防止系统在不知情情况下"悄悄改变自己"的基础设施。

---

### 19.6 专家知识注入协议（Expert Priming Protocol）

系统的 Semantic Memory（原则层）不应只靠机器自己总结。应提供：

- 人工输入高质量"原则"的接口（交易员的直觉规则、风险经验）
- 这些人类经验以 `system_principle` 存入记忆，享有高权重
- 系统在每次 deliberation 时召回相关原则
- 当系统行为与某条原则冲突时，自动触发解释请求

这形成了"人机共同认知权威"的架构，而不是纯粹的 AI 自治。

---

### 19.7 实验治理量化标准（Research Governance with Frequentist / Bayesian Switching）

当前 Research Loop 的实验判断标准未被定义。建议：

- **小样本实验（< 30 例）**：贝叶斯更新（Beta 分布先验）
- **大样本实验（> 100 例）**：标准频率统计（t-test, p < 0.05）
- 自动选择检验方法，并在研究结论中附带置信区间

这让"假设是否被接受"有了可审计的统计标准，而不是依赖 LLM 的主观判断。

---

## 20. 综合评审结论

| 评估维度 | 结论 | 关键条件 |
| -------- | ---- | -------- |
| LLM 原生量化平台理念可行性 | ✅ 可行 | 限定日线及以上时间框架；α 归因需实证验证 |
| 本方案架构合理性 | ✅ 方向正确 | 需补充时间尺度分层、幻觉防护、可证伪世界模型 |
| 月度运营成本 | ✅ 可接受 | DeepSeek 主力路线：$400–650/月；模型选择决定 LLM 成本量级 |
| 基于当前平台改造可行性 | ✅ 强烈推荐 | 需对 `AutonomousEngine` 做一次计划内战略拆分 |
| 从零重建 | ❌ 不建议 | 12–24 个月成本，放弃现有生产级风控资产 |
| 方案文档整体质量 | 7/10 | 愿景清晰，工程细节不足；G1–G5 结构性缺失需补充 |

**评审团最终定性：**

> 本文档是一份优秀的**战略愿景文档**，但要成为可执行的工程路线图，还需要补充 α 验证框架（G1）、时间尺度分层（G2）、记忆遗忘机制（G3）、幻觉防护层（G4），以及 Human-in-the-loop escalation 协议（G5）。第 19 节列出的七个前沿演进方向（Theory of Mind、反事实引擎、Belief Graph、异步预计算认知、认知漂移监控、专家知识注入、研究治理量化标准）值得结合实际验证情况纳入后续版本迭代。
