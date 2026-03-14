# V11.1.1 Release Plan — Trader Workbench Convergence & Architecture Simplification

> AI量化交易闭环系统 — V11.1.1 规划说明  
> 文档版本：Draft v1.0 | 初稿日期：2026-03-14 | 状态：规划提案  
> 当前规划基线：V11.0.1 Capital Velocity & Autonomous Evolution OS  
> 核心命题：**从“功能持续堆叠”切换到“工作台收敛、架构清晰、代码减重、体验升级、治理可持续”的下一阶段平台化治理。**  
> 本规划直接回应两个核心诉求：1）站在顶尖量化平台产品、交易经理、交易员视角，进一步治理平台功能页面，收敛系统并提升体验；2）站在架构师视角，系统性治理前后端架构与代码，确保设计清晰、实现优雅、性能良好、复用度高、复杂度低并符合最佳实践。

---

## 0. 版本定位

### 0.1 一句话定义

V11.1.1 是一次 **Trader Workbench Convergence & Architecture Simplification** 升级：

> 让平台从“已经很强、但越来越重”的个人量化系统，升级为一套**更像顶尖交易团队工作台**的产品：页面更聚焦、信息更一致、路径更短、架构更清晰、代码更轻、更快、更易维护。

### 0.2 为什么是 V11.1.1

V11.0.1 已经解决了以下问题：

- 为什么资金闲置；
- 为什么信号被卡住；
- 哪里值得改进。

而 V11.1.1 要解决的是另一类更基础、也更长期的问题：

- 为什么同一问题需要在多个页面来回跳转才能看清；
- 为什么前后端边界越来越宽，新增能力越来越依赖“并排加文件”；
- 为什么兼容层、历史路由、legacy 状态和并行视图越来越多；
- 为什么系统越强，维护成本却越高。

换句话说：

- **V11.0.1** 在增强“系统自知与资本效率”；
- **V11.1.1** 则要增强“产品可控性、架构可治理性与工程可持续性”。

### 0.3 当前代码与工作台的现实诊断

基于本次仓库核查，当前系统已经具备明显的“平台成熟期治理信号”：

#### 代码体量信号（本次核查，仅计 .py / .vue 源文件，不含 .pyc 编译缓存）

| 区域 | 当前规模（源文件） |
| ---- | ---- |
| 后端 `app/services` | 100 个 .py |
| 后端 `app/routers` | 47 个 .py |
| 后端 `app/models` | 51 个 .py |
| 后端 `app/jobs` | 35 个 .py |
| 前端 `src/views` | 53 个 .vue |
| 前端 `src/components` | 86 个 .vue/.ts |
| 前端 `src/api` | 28 个 .ts |
| 前端 `src/stores` | 19 个 .ts |

> **注**：若含 `__pycache__/*.pyc` 则数量翻倍（约 195 / 95 / 102），但编译缓存不代表代码复杂度，以上数据为有效代码基线。

#### 结构与体验信号（本次核查）

- `src/router/index.ts` 中存在 **18 条** legacy redirect 别名（不含根路径 `/` 重定向），说明页面治理已进入"收口期"。
- 前端仍可见 `legacy compat` 逻辑，如 `src/stores/lifecycle.ts`、`src/api/positionLifecycleService.ts`。
- 后端仍存在 legacy / compat 暴露，如 `app/routers/quant_loop.py` 的 deprecated 自动执行入口、`app/routers/autonomy.py` 中的 `LEGACY_COMPAT` / `LEGACY_NONE` 语义。
- 当前页面和接口已经不缺"能力"，真正缺的是：**主路径、归属感、一致性、层次感、可维护性**。

#### 前端孤儿视图清单（无活跃路由，待清理）

以下 `.vue` 文件存在于 `src/views/` 但在 `src/router/index.ts` 中无任何活跃路由指向（部分仅残留 legacy redirect 的来源端），属于死代码：

| 文件 | 现状说明 |
| ---- | -------- |
| `DashboardPage.vue` | V9 旧仪表盘，当前路由已切换至 `DashboardV2Page.vue` |
| `AIAdvisorPage.vue` | 老版 AI 建议页，`/ai-advisor` 已 redirect 至 `/autonomy` |
| `AiAdvicePage.vue` | AI 建议另一个版本，无任何路由引用 |
| `ExecutionCenter.vue` | 旧执行中心，`/execution-center` 已 redirect 至 `/autonomy` |
| `ExecutionListPage.vue` | 执行列表孤立版本，无活跃路由 |
| `AlgoExecutionPage.vue` | 无路由，功能已被 `/execution-policy` 覆盖 |
| `StressTestPage.vue` | `/stress-test` redirect 至 `/backtest`，本文件冗余 |
| `BehaviorScorePage.vue` | 无路由，行为评分功能已归并 |
| `MarketHotspotsPage.vue` | `/hotspots` redirect 至 `/opportunities`，本文件冗余 |
| `ApiMonitoringPage.vue` | `/api-monitoring` redirect 至 `/system-monitor?tab=api` |
| `ServiceHealthPage.vue` | `/service-health` redirect 至 `/system-monitor?tab=health` |
| `SystemHealthPage.vue` | 无路由，系统健康已在 `SystemMonitorPage` 覆盖 |
| `ExternalApiMonitoringPage.vue` | 无路由，冗余监控视图 |

> **结论**：在真正做"功能收敛"之前，先**删除上述 13 个孤儿文件**，前端视图数可从 53 降至 **40**，显著低于 V11.1.1 的 ≤ 40 目标。后续"功能页合并"才是真正的体验收敛工作，而不是靠删除孤儿文件凑数。

#### 后端 Legacy 路由登记现状

以下后端路由文件在 `app/main.py` 中仍处于**活跃注册**状态，但对应的前端页面已废弃或重定向：

| 路由文件 | API prefix | 现状 |
| -------- | ---------- | ---- |
| `ai_advisor.py` | `/api/v1/ai-advisor/...` | 对应前端 `/ai-advisor` → 已 redirect 到 `/autonomy` |
| `execution_center.py` | `/api/v1/execution-center/...` | 对应前端 `/execution-center` → 已 redirect 到 `/autonomy` |
| `hotspots.py` | `/api/v1/hotspots/...` | 对应前端 `/hotspots` → 已 redirect 到 `/opportunities` |
| `dashboard.py` | `/api/v1/dashboard/...` (V9) | 与 `dashboard_v2.py` 并存，V9 版本已无前端对应 |
| `stress_test.py` | `/api/v1/stress-test/...` | 对应前端 `/stress-test` → 已 redirect 到 `/backtest` |

> V11.1.1 必须给出以上 5 个 legacy 后端路由的 sunset 或迁移计划，而不是让它们永久注册在 `main.py` 中。

### 0.4 V11.1.1 不可妥协的边界

V11.1.1 必须同时满足以下边界：

1. **不放宽风险控制**：不得通过弱化 RiskGate、容量纪律或治理门槛来换取“流程更顺”。
2. **不做无边界重写**：优先做结构收敛与边界治理，不做“全仓重构式豪赌”。
3. **不制造新并行体系**：不得在现有页面、现有服务旁再造一个近似平行的新系统。
4. **不牺牲可解释性**：所有合并、抽象与重构都必须保留结果值、解释字段、来源、数据质量与建议动作。
5. **不牺牲发布安全**：所有体验收敛与架构治理必须支持 feature flag、灰度和回退。

---

## 1. 版本目标

### 1.1 顶层目标

V11.1.1 的顶层目标不是“新增更多功能页”，而是：

- 让用户在更少页面中完成更多高价值动作；
- 让交易经理能在一套统一工作台上完成监控、解释、决策与治理；
- 让交易员能在更短路径中完成下钻、确认、回放与干预；
- 让前后端在更清晰边界上持续扩展，而不是继续平铺膨胀；
- 让新功能以更低复杂度、更高复用度进入系统。

### 1.2 四条设计原则

| 原则 | 含义 | 对应要求 |
| ---- | ---- | -------- |
| 架构清晰 | 领域边界明确、依赖方向稳定、读写职责分离 | 新能力优先进入已有上下文，不新增平行抽象 |
| 体验收敛 | 一类问题有唯一主界面，一类动作有唯一主入口 | 页面治理优先于继续扩页 |
| 性能优先 | 用更优雅的数据组织与渲染策略取代“堆接口、堆组件” | P95、缓存、批量化、虚拟化成为默认纪律 |
| 最佳实践 | 低耦合、高复用、低复杂度、注释克制但充分 | 新代码默认遵守 contract-first、typed、可测、可灰度 |

### 1.3 成功标准

V11.1.1 的成功不以"又加了多少页"来衡量，而以以下可量化指标衡量：

| 维度 | 基线 | 目标 | 量化验收方式 |
| ---- | ---- | ---- | ------------ |
| 前端视图文件数 | 53 .vue | **≤ 40** | `src/views/` 文件计数 |
| legacy redirect alias 数 | 18 条 | **≤ 10** | `src/router/index.ts` redirect 计数 |
| 后端活跃 legacy 路由 | 5 个待处置 | **≤ 2** | `app/main.py` include_router 清单 |
| 关键工作台的 explainability strip 覆盖 | 0（无统一标准） | **A/C/D 域主页面全覆盖** | 手工验收截图 |
| 核心问题是否有唯一主入口 | 多入口/分散 | **Page Ownership Matrix 定稿** | 文档评审 |
| backend read model 覆盖 | 0 | **≥ 3 个核心工作台** | 接口文档 |
| 重点页面性能（非 AI 接口 P95） | 未建立基线 | **< 400ms** | 实测或压测 |

---

## 2. 角色视角下的产品工作台治理

### 2.1 顶尖量化平台产品视角：从“页面集合”升级为“工作台体系”

顶尖量化平台的核心不是页面多，而是：

- **同一问题的答案高度集中**；
- **同一动作的发起点高度稳定**；
- **同一结论在不同工作台中口径一致**；
- **状态、解释、证据和行动建议同屏联动**。

因此，V11.1.1 要把当前系统收敛为四大工作台域，而不是继续增加导航碎片：

#### Workbench A — Command Center（总控中枢）

围绕以下页面收敛：

- `/dashboard`
- `/war-room`
- `/autonomy`

目标：

- `dashboard` 负责“全局一屏摘要”；
- `war-room` 负责“盘中高密度态势”；
- `autonomy` 负责“系统解释、自知画像、治理状态与控制”。

禁止再出现新的“全局摘要型”页面与平行总控入口。

#### Workbench B — Research & Allocation（研究与配置中枢）

围绕以下页面收敛：

- `/alpha-lab`
- `/portfolio`
- `/opportunities`
- `/macro`
- `/regime`

目标：

- 统一回答“哪里值得研究、为什么值得、如何配资本、为什么没配更多”。
- 所有研究结论最终都能落到 seat / risk budget / capital usage 的解释链上。

#### Workbench C — Execution & Lifecycle（执行与生命周期中枢）

围绕以下页面收敛：

- `/order-book`
- `/execution-policy`
- `/trade-lifecycle`
- `/positions`
- `/position-evaluation`

目标：

- `order-book` 成为交易动作主入口；
- `execution-policy` 负责交易前后执行解释；
- `trade-lifecycle` 负责链路过程；
- `positions` / `position-evaluation` 收敛成“持仓与执行后状态”统一视角。

#### Workbench D — Governance & Operations（治理与运营中枢）

围绕以下页面收敛：

- `/governance/pipeline`
- `/evolution`
- `/system-monitor`
- `/copilot`
- `/task-management`

目标：

- 把治理、运维、学习与操作助手统一成一个“运营中枢”；
- `task-management` 不再作为长期独立导航存在，应逐步并入 `/system-monitor` 的任务/作业视图；
- `copilot` 从“聊天页”升级为跨工作台入口。

### 2.2 完整页面 → 工作台归属映射（清理孤儿后的 40 个活跃页面）

> 以下映射基于清理 13 个孤儿视图后的实际活跃路由（38 条活跃路由 + 2 条系统路由），与当前前端 4 组导航结构对齐，同时说明 V11.1.1 工作台 Domain 归属。

| 页面路由 | 当前导航分组 | V11.1.1 工作台 | V11.1.1 动作 |
| -------- | ------------ | -------------- | ------------ |
| `/dashboard` | 指挥室 | A — Command Center | 保留，作全局摘要主入口 |
| `/war-room` | 交易中枢 | A — Command Center | 保留，统一 shell 与 Dashboard |
| `/autonomy` | AI 洞察&系统 | A — Command Center | 保留，治理/自知/控制主入口 |
| `/order-book` | 交易中枢 | C — Execution & Lifecycle | 保留，交易动作唯一主入口 |
| `/execution-policy` | 交易中枢 | C — Execution & Lifecycle | 保留，成本/策略回放主入口 |
| `/trade-lifecycle` | 交易中枢 | C — Execution & Lifecycle | 保留，链路过程主入口 |
| `/positions` | 交易中枢 | C — Execution & Lifecycle | 与 `/position-evaluation` 收敛为双视角 |
| `/position-evaluation` | 交易中枢 | C — Execution & Lifecycle | 与 `/positions` 收敛 |
| `/observability/execution` | 交易中枢 | C — Execution & Lifecycle | 保留为执行深度子页面 |
| `/observability/signal` | 交易中枢 | C — Execution & Lifecycle | 保留为信号深度子页面 |
| `/observability/risk` | 交易中枢 | C — Execution & Lifecycle | 保留为风险深度子页面 |
| `/signal-watchtower` | 交易中枢 | C — Execution & Lifecycle | 保留（V10.4.2 核心功能） |
| `/attribution` | 交易中枢 | C — Execution & Lifecycle | 保留，执行后归因 |
| `/paper` | 交易中枢 | C — Execution & Lifecycle | 保留，研究→生产通道 |
| `/quant-loop` | 交易中枢 | D — Governance & Ops | 后端已 deprecated 主路径，前端保留可观测视图，对应 legacy sunset |
| `/alpha-lab` | 研究&分析 | B — Research & Allocation | 保留，研究核心工作台 |
| `/portfolio` | 研究&分析 | B — Research & Allocation | 保留，动态组合构建主入口 |
| `/opportunities` | 研究&分析 | B — Research & Allocation | 保留，机会扫描主入口 |
| `/macro` | 研究&分析 | B — Research & Allocation | 保留 |
| `/regime` | AI 洞察&系统 | B — Research & Allocation | 迁移归属 B（体制感知是研究输入） |
| `/strategies` | 研究&分析 | B — Research & Allocation | 保留 |
| `/strategies/:id` | 研究&分析 | B — Research & Allocation | 保留（子路由） |
| `/backtest` | 研究&分析 | B — Research & Allocation | 保留 |
| `/etf-pool` | 研究&分析 | B — Research & Allocation | 保留 |
| `/options` | 研究&分析 | B — Research & Allocation | 保留 |
| `/governance/pipeline` | AI 洞察&系统 | D — Governance & Ops | 保留，策略晋级主入口 |
| `/evolution` | AI 洞察&系统 | D — Governance & Ops | 保留，AI 进化 |
| `/system-monitor` | AI 洞察&系统 | D — Governance & Ops | 保留，与 `/task-management` 收敛 |
| `/task-management` | AI 洞察&系统 | D — Governance & Ops | 收口到 `/system-monitor` 多 Tab |
| `/copilot` | AI 洞察&系统 | D — Governance & Ops | 升级为跨工作台入口 |
| `/live-safety` | AI 洞察&系统 | D — Governance & Ops | 保留（AI 安全监控） |
| `/ai-hub/agents` | AI 洞察&系统 | D — Governance & Ops | 保留（治理/观测深度子页） |
| `/ai-hub/calibration` | AI 洞察&系统 | D — Governance & Ops | 保留 |
| `/ai-hub/weights` | AI 洞察&系统 | D — Governance & Ops | 保留（因子自适应） |
| `/ai-hub/post-mortem` | AI 洞察&系统 | D — Governance & Ops | 保留 |
| `/events` | 交易中枢 | B — Research & Allocation | 迁移归属 B（事件日历是研究/风险输入） |
| `/alerts` | AI 洞察&系统 | D — Governance & Ops | 保留 |
| `/journal` | AI 洞察&系统 | C — Execution & Lifecycle | 迁移归属 C（交易日志是执行后审计），后续可考虑并入 `/order-book` 历史 Tab |
| `/login` | 系统 | — 系统路由 — | 不变 |

> **说明**：上表说明工作台 Domain 是**逻辑归属与开发迭代优先级**，不代表前端导航组必须重组为 4 组新名称。V11.1.1 可在保持当前 4 组导航结构的前提下进行工作台收敛，导航重组是可选的下一阶段工作。

### 2.3 交易经理视角：需要的是统一决策面，而不是更多图表

交易经理最关心的是：

- 当前资本是否被合理分配；
- 当前风险预算是否被低效占用；
- 当前哪些策略/执行/治理节点正在拖累收益；
- 当前是否存在必须人工介入的异常。

V11.1.1 对应要求：

- 每个核心工作台必须提供 **headline summary + blocker list + suggested action** 三段结构；
- 所有重大结论必须标明：**来源类型 / 数据质量 / 最后更新时间 / 推荐动作**；
- 所有治理结论必须能下钻到证据链，而不是只给状态颜色。

### 2.4 交易员视角：需要的是快、准、稳、少打断

交易员最关心的是：

- 订单现在在哪个阶段；
- 为什么被缩量、拒绝、降级或延迟；
- 现在应该改什么，在哪里改；
- 看清链路时不要跨 3~5 个页面来回跳。

V11.1.1 对应要求：

- `order-book` 成为执行动作唯一主入口；
- `trade-lifecycle` 成为过程解释唯一主入口；
- `execution-policy` 成为成本/策略回放唯一主入口；
- 对同一笔交易，三个页面之间必须支持深链与统一 ID/状态语义。

---

## 3. M1 — Platform UX Governance & Page Convergence

### M1 目标

通过页面治理而不是继续扩页，把当前系统从“功能丰富但分散”收敛成“问题导向、角色友好、路径清晰”的工作台体系。

### M1 核心能力

#### 1. Page Ownership Matrix（页面归属矩阵）

为每类核心问题设定唯一主入口：

| 问题类型 | 唯一主入口 | 辅助入口 |
| -------- | ---------- | -------- |
| 系统当前是否健康 | `/dashboard` / `/war-room` | `/system-monitor` |
| 为什么资金没转起来 | `/autonomy` / `/portfolio` | `/alpha-lab` |
| 这笔订单为什么这样执行 | `/execution-policy` | `/order-book` |
| 这笔交易现在卡在哪一步 | `/trade-lifecycle` | `/order-book` |
| 为什么某策略能/不能晋级 | `/governance/pipeline` | `/evolution` |
| 现在该人工介入什么 | `/dashboard` / `/system-monitor` | `/copilot` |

#### 2. Convergence Candidates（优先收敛对象）

V11.1.1 的收敛工作分两个层次，依次执行，不能混淆：

##### 层次一：孤儿文件删除（无风险，先行）

直接删除以下 13 个无活跃路由的死代码文件；删除后视图数从 53 → 40，redirect alias 可从 18 → **≤ 10**：

前端视图删除清单：

- `DashboardPage.vue`、`AIAdvisorPage.vue`、`AiAdvicePage.vue`
- `ExecutionCenter.vue`、`ExecutionListPage.vue`、`AlgoExecutionPage.vue`
- `StressTestPage.vue`、`BehaviorScorePage.vue`、`MarketHotspotsPage.vue`
- `ApiMonitoringPage.vue`、`ServiceHealthPage.vue`、`SystemHealthPage.vue`、`ExternalApiMonitoringPage.vue`

配套移除的 redirect 路由（随删除文件一起清理，可降至 ≤ 10 条）：

- `/hotspots`、`/behavior`、`/ai-advisor`、`/execution-center`、`/stress-test`、`/execution-algo`、`/plans`、`/dashboard-v1`

保留的合理 redirect（共 ≤ 10 条）：

- `/api-monitoring`、`/service-health`、`/monitoring`、`/system` → 系统类简写
- `/observability/execution-microscope`、`/observability/signal-intelligence`、`/observability/risk-cluster` → 文档 URL 对齐
- `/ai-hub/factor-weights`、`/ai-hub/post-mortems`、`/advice` → 命名演化兼容

##### 层次二：功能页合并（有 UX 风险，需设计方案后再执行）

以下是真正意义上的"功能收口"，每一对都必须先出设计稿再实施：

- `system-monitor` + `task-management` → 单页多 Tab
- `positions` + `position-evaluation` → 单工作台双视角（汇总视角 + 评估视角）
- `dashboard` + `war-room` → 统一 shell、统一过滤、统一摘要卡（两个路由可保留，共享壳层）
- `order-book` + `execution-policy` + `trade-lifecycle` → 统一对象 ID、统一联动面包屑
- `journal` → 并入 `/order-book` 历史审计 Tab（交易日志是执行后数据的另一个视角）

#### 3. Explainability Strip（解释条）

所有关键工作台新增统一信息行：

- 结果值
- 解释字段
- 来源类型
- 数据质量
- 最后更新时间
- 建议动作

任何核心结论都不允许只给数值、不解释原因。

#### 4. State Discipline（页面状态纪律）

所有工作台统一支持：

- loading
- empty
- error
- degraded
- stale-but-usable

避免“有接口但没状态语言”的不完整体验。

### M1 验收标准

- [ ] 13 个孤儿视图文件已从 `src/views/` 删除，视图总数从 53 → **≤ 40**
- [ ] redirect-only 历史别名路由从 18 条减少至 **≤ 10**，且每条保留的 redirect 都有明确保留理由
- [ ] 核心问题均有唯一主入口（见 §3 M1 Page Ownership Matrix），不存在多个平行主入口
- [ ] 关键工作台（至少 A/C/D 域主页面）全部具备统一的 explainability strip
- [ ] `system-monitor` 与 `task-management` 完成结构收口为单页多 Tab，不再并行为两个独立导航入口
- [ ] 5 个 legacy 后端路由（`ai_advisor.py`、`execution_center.py`、`hotspots.py`、`dashboard.py` V9、`stress_test.py`）均已从 `app/main.py` 移除注册或转为按 flag 按需挂载

---

## 4. M2 — Frontend Architecture Governance

### M2 目标

在不更换 Vue 3 + TypeScript + Vite 主栈的前提下，治理前端目录、状态、接口消费与页面壳层，使前端从“页面驱动增长”转向“工作台驱动演进”。

### M2 核心能力

#### 1. Thin Views, Fat Workbench Modules

治理原则：

- `src/views/*` 只负责页面级编排；
- 复杂面板、表格、过滤器、摘要条、解释卡片进入领域组件；
- store 只存跨组件共享状态，不承载过多推导与兼容逻辑；
- 网络请求不在视图层散落调用。

建议结构：

- `src/views/`：薄页面
- `src/components/workbench/`：统一壳层与共享组件
- `src/components/<domain>/`：领域组件
- `src/api/contracts/`：接口契约与 DTO 适配
- `src/stores/`：按领域收敛 store，而不是按页面增长

#### 2. Contract-First API Consumption

当前前端已经有较多 API service 文件，V11.1.1 需要进一步收敛为：

- 以后端 OpenAPI / Pydantic schema 为契约源；
- 前端维护 typed DTO 映射层；
- 页面不直接吃“原始后端拼装对象”；
- 对需要长期演进的工作台接口，优先引入稳定 DTO，而不是让页面适配各种兼容字段。

#### 3. Shared Workbench Shell

新增统一页面壳层能力：

- 统一标题区
- 统一全局过滤器位置
- 统一 summary cards 区
- 统一更新时间/数据质量/降级状态展示
- 统一右侧 detail drawer 模式

减少每个页面自定义一套头部、筛选区、摘要区的重复成本。

#### 4. Legacy Compatibility Sunset Plan

以下兼容逻辑不应永久存在：

- legacy route alias
- legacy FSM compat state
- backward-compatible 页面专属 API 调用路径
- 只为历史页面保留的新旧字段并存状态

V11.1.1 必须给出明确 sunset 清单：

- 哪些兼容在本版本移除；
- 哪些兼容保留但标记 sunset deadline；
- 哪些兼容继续存在但必须转为 adapter 层而非 UI 层显式判断。

#### 5. Frontend Performance Discipline

前端默认遵守：

- 大表格虚拟化/分段渲染
- 重图表页面按 Tab/可见性懒加载
- 请求可取消（避免切页后无效返回覆盖状态）
- 同域数据请求聚合与去重
- WebSocket / SSE 生命周期统一管理

#### 6. Mobile-First Compliance

本系统明确要求 mobile-first 多断点支持，V11.1.1 的 workbench shell 设计必须满足：

- 统一壳层（标题区、过滤器、summary cards、detail drawer）在 375px 竖屏下可用，无横向溢出
- 新增或重构的工作台组件必须在移动断点下提供可用的降级布局，不能只验收桌面态
- 不得引入仅适用于宽屏的布局假设（如固定宽度多列 grid、hover-only 动作入口）
- V11.0.1 已交付的移动触达能力（Dashboard/Alert/Copilot 竖屏）在收敛后必须保持完好

#### 7. V11.0.1 特性保护

V11.0.1 在 `/autonomy` 中刚落地的系统自知画像（MetaState、FrictionState、FalseHoldAlerts、ImprovementCandidates）是 V11.1.1 工作台收敛的**基础展示层**：

- 合并或重构 `/autonomy` 时，上述 4 个新增面板的信息密度不得降低；
- 其后端接口（`/api/v1/autonomy/meta-state` 等）不在本版本 sunset 范围内；
- 如 `/autonomy` 被纳入统一 shell，shell 设计须能容纳这些面板的展开/收起交互。

### M2 验收标准

- [ ] 所有核心视图实现 thin-view 模式，复杂交互下沉到领域组件或共享工作台组件
- [ ] 新增/重构页面全部使用统一 workbench shell
- [ ] 关键工作台接口具备 typed contract 层
- [ ] legacy compat 判断不再散落在多个页面和 store 中
- [ ] 重点页面都能明确展示 loading / empty / error / degraded / stale 五类状态

---

## 5. M3 — Backend Domain Architecture Governance

### M3 目标

在保持 FastAPI + service-oriented 主结构不变的前提下，治理后端边界、编排入口、查询模型和服务分层，让后端从“平铺增长”转向“领域收敛”。

### M3 核心能力

#### 1. Bounded Contexts Inside `app/services` & `app/engine`

后端继续保留 `app/services` 作为主目录，但不再无限平铺；V11.1.1 按上下文治理为子域：

- `autonomy`
- `research`
- `portfolio`
- `execution`
- `governance`
- `observability`
- `platform`（scheduler / config / health / integrations）

**`app/engine/` 的定位须明确**：当前 `app/engine/` 目录包含核心编排组件（`autonomous_engine.py`、`signal_engine.py`、`signal_quality_funnel.py`、`order_executor.py`、`quant_trading_loop.py` 等），是整个系统的决策与执行核心。V11.1.1 需要明确其与 `app/services` 的分层关系：

- `app/engine/` = **编排层**（Orchestration Layer）：跨域协调、主决策循环、质量漏斗
- `app/services/` = **领域服务层**（Domain Services）：单域业务规则与 I/O
- 边界规则：`engine` 可调用 `services`，`services` 不应反向依赖 `engine`；新增编排能力进 `engine`，新增业务规则进对应 `services/<context>/`

这不是引入新框架，而是在当前结构内建立清晰边界。

#### 2. Thin Routers, Explicit Application Services

当前 router 数量已较多，V11.1.1 要求：

- router 只负责 request/response、权限、参数校验；
- 编排进入 application service；
- domain service 只处理业务规则；
- adapter 负责 Tiger / Redis / LLM / 外部接口。

禁止在 router 中继续堆查询拼装与兼容判断。

#### 3. Workbench Read Models

面向工作台的高密度视图，优先引入 read model / query service：

- `dashboard` / `war-room`
- `order-book`
- `execution-policy`
- `system-monitor`
- `governance/pipeline`

目标：

- 把“给页面拼数据”的职责从纯业务写模型中隔离出来；
- 减少一个页面打 4~8 个接口再拼的复杂度；
- 让后端对工作台负责，而不是让前端承担过多聚合成本。

#### 4. Single Orchestration Path Discipline

V11.1.1 要继续收紧“唯一主链路”原则：

- 自动交易主编排继续以 `AutonomousEngine.run_decision_cycle()` 为唯一主链；
- legacy `quant_loop` 旁路（`POST /execute-signals` deprecated 端点）前后端双侧同步进入 sunset：
  - 后端：从 `app/main.py` 注册移除，或保留但强制 flag-gate 为 disabled；
  - 前端：`/quant-loop` 页面降为只读观测视图（不再提供手动触发执行的操作）；
- 新功能不得再新增第二套决策/执行入口。

#### 5. Legacy Backend Router Sunset

以下 5 个 legacy 路由文件须在本版本给出明确处置方案（至少标注 sunset deadline，本版本内完成其中 ≥ 3 个的移除）：

| 文件 | 处置方案 |
| ---- | -------- |
| `ai_advisor.py` | 迁移剩余有效端点至 `autonomy.py`，然后从 `main.py` 移除注册 |
| `execution_center.py` | 检查是否有存活调用方；如无，直接从 `main.py` 移除注册 |
| `hotspots.py` | 确认前端已全部切换至 `/opportunities`，从 `main.py` 移除注册 |
| `dashboard.py` (V9) | 保留注册但标记为 `deprecated=True`，后续版本删除 |
| `stress_test.py` | 子功能迁移至 `/backtest` 后端，从 `main.py` 移除注册 |

#### 5. Scheduler & Job Governance

作业层继续扩展，但必须治理：

- Job 注册统一登记
- Job 输入输出契约清晰
- 幂等、超时、补跑、回放统一处理
- 任务状态既能服务运维，也能服务工作台展示

### M3 验收标准

- [ ] 新增/重构服务按 bounded context 组织，不再继续平铺式增长
- [ ] router 实现薄化，复杂编排逻辑迁移到 application service
- [ ] 核心工作台具备专属 read model / query service，而不是由前端承担多端聚合
- [ ] legacy 旁路编排进入 sunset 计划并给出正式替代说明
- [ ] Job 注册、健康、超时、补跑信息能被系统监控统一消费

---

## 6. M4 — Code Quality, Reuse & Performance Standards

### M4 目标

用工程纪律而不是个人英雄主义，保证代码优雅、高性能、可复用、可阅读、可演进。

### M4 核心能力

#### 1. Complexity Budget

V11.1.1 引入明确的复杂度预算：

- 新增核心模块优先控制为单职责
- 单函数避免过深嵌套
- 复杂分支优先拆成小型纯函数
- 同类状态映射、徽章逻辑、DTO 转换逻辑禁止分散复制

#### 2. Reuse by Design

复用优先级：

1. 统一 schema / DTO
2. 统一 query builder / serializer
3. 统一状态组件 / 表格列定义 / badge 映射
4. 统一 feature flag / config 读取方式
5. 统一错误模型与日志字段

#### 3. Comment Policy

注释要求：

- 注释解释 **为什么**，不是翻译代码在做什么；
- 对复杂金融语义、风险语义、编排语义必须写清边界；
- 对临时兼容、迁移桥接、deprecation 必须写 sunset 理由与移除条件；
- 注释简洁，不写“流水账型注释”。

#### 4. Performance Budgets

V11.1.1 建议目标：

- 非 AI 查询接口：P95 < 400ms
- 复杂工作台聚合接口：P95 < 900ms
- 关键列表首屏渲染：P95 < 2.5s
- 热路径页面切换：尽量避免重复请求同一摘要数据
- 大表格默认分页或虚拟化，不允许“全量硬渲染”成为默认实现

#### 5. Test & Contract Discipline

V11.1.1 需要补齐四层校验：

- unit tests：纯业务规则
- contract tests：前后端 DTO / schema
- integration tests：工作台聚合接口、作业编排、治理链路
- build / lint / smoke：前端构建、后端重点回归、关键文档对齐

### M4 验收标准

- [ ] 新增代码遵守统一复杂度预算与复用优先级
- [ ] 工作台核心逻辑具备 contract test 或等价验证
- [ ] 复杂金融/治理逻辑具备简洁但充分的边界注释
- [ ] 性能热点页面与接口有明确预算并具备可观测指标
- [ ] 不再以复制粘贴方式维护相近 badge / status / DTO / mapping 逻辑

---

## 7. M5 — Delivery Strategy & Release Slices

### M5 目标

让 V11.1.1 成为一次可灰度、可回退、可验证的治理版本，而不是一次高风险“大修”。

### Stage 0 — Orphan Cleanup（前置清理，可立即执行，无需设计评审）

- 删除 13 个孤儿视图文件（见 §0.3 孤儿清单）
- 清理与之关联的 8 条 redirect alias（见 M1 §2 层次一清单）
- 确认 5 个 legacy 后端路由的迁移或移除计划（至少形成文字决策记录）
- **完成条件**：前端视图数 ≤ 40，redirect alias ≤ 10，`npm run build` 通过，无 import 残留

### Stage A — Inventory & Decision Records

- 页面归属矩阵定稿（以 §2.2 映射表为初稿，审查并更新）
- legacy alias / compat 清单定稿（Stage 0 执行后更新汇总）
- bounded context 划分定稿（包含 `app/engine/` vs `app/services/` 边界）
- 关键工作台 read model 清单定稿
- ADR（Architecture Decision Record）开始落库到 `docs/architecture/decisions/`

### Stage B — Frontend Workbench Convergence

- 收敛高价值重叠页面（优先 system-monitor+task-management、positions+position-evaluation）
- 引入 shared workbench shell（桌面 + 移动双断点验收）
- 完成重点页面的统一状态机和 explainability strip
- 清理残余 legacy 路由与 UI 层 compat 判断

### Stage C — Backend Query & Domain Refactor

- 引入核心工作台 read models
- 收敛 router/application/domain/adapters 分层（`app/routers` 薄化）
- 完成 Stage 0 中未完成的 legacy 后端路由迁移
- 统一日志、错误、契约出口

### Stage D — Sunset & Hardening

- 下线已完成替代的 legacy alias / compat 路径
- 跑通前后端构建、重点回归与工作台验收
- 完成文档、路线图、迁移说明与回退说明

### 建议 Feature Flags

- `WORKBENCH_CONVERGENCE_V1111_ENABLED`
- `FRONTEND_SHELL_V1111_ENABLED`
- `READ_MODEL_V1111_ENABLED`
- `ARCH_GOVERNANCE_V1111_ENABLED`
- `LEGACY_SUNSET_V1111_ENABLED`

> 所有 flag 均默认安全关闭；收敛类改动优先以 UI/查询层灰度，不直接改动交易风险语义。

---

## 8. 统一验收矩阵

### 8.1 产品与用户体验

- [ ] 核心问题均有唯一主入口
- [ ] 关键工作台统一显示结果、解释、来源、数据质量、建议动作
- [ ] 页面收敛后，核心路径点击数明显下降
- [ ] 没有新增一级导航膨胀

### 8.2 前端架构

- [ ] 核心工作台进入统一 shell
- [ ] 重点页面 thin-view 化
- [ ] typed contract 层覆盖关键工作台
- [ ] legacy compat 显著收敛

### 8.3 后端架构

- [ ] bounded context 目录化落地
- [ ] router/application/domain/adapters 分层更清晰
- [ ] 工作台 read models 落地
- [ ] legacy orchestrator 路径完成 sunset 计划

### 8.4 代码质量与工程治理

- [ ] 新代码复用优先、复杂度受控、注释边界清晰
- [ ] 性能预算被纳入验收
- [ ] 文档、实现、路由与接口口径一致
- [ ] 不引入新的永久兼容债务

---

## 9. 非目标（明确边界）

V11.1.1 当前**不以**以下事项为主目标：

1. 继续横向扩张页面数量
2. 为了“更现代”而更换核心技术栈
3. 在没有边界设计的前提下整体重写前后端
4. 为了简化页面而牺牲交易、风险、治理细节
5. 为了视觉改版而破坏现有控制平面与接口稳定性

---

## 10. 最终判断

V11.1.1 不是一个“多加几个功能”的版本，而是一个**平台治理版本**。

它要回答的不是：

- 还能不能再做更多能力；

而是：

- 当前这些能力，是否已经组织成了真正的顶尖量化交易工作台；
- 当前这套前后端结构，是否还能优雅地支撑未来 2~3 个版本持续演进；
- 当前这份代码，是否让后续开发是在“建设系统”，而不是“绕着历史复杂度继续堆”。

如果 V11.0.1 的关键价值是让系统开始“理解自己”，那么 V11.1.1 的关键价值就是：

> **让这套系统在产品体验、前后端架构与工程质量上，也开始像一支顶尖交易团队一样运作：边界清晰、动作统一、解释充分、执行高效、治理可持续。**
