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

#### 代码体量信号（本次核查）

| 区域 | 当前规模 |
| ---- | -------- |
| 后端 `app/services` | 195 个文件 |
| 后端 `app/routers` | 95 个文件 |
| 后端 `app/models` | 102 个文件 |
| 后端 `app/jobs` | 35 个文件 |
| 前端 `src/views` | 53 个文件 |
| 前端 `src/components` | 86 个文件 |
| 前端 `src/api` | 28 个文件 |
| 前端 `src/stores` | 19 个文件 |

#### 结构与体验信号（本次核查）

- `src/router/index.ts` 中存在较多别名重定向与历史路由兼容入口，说明页面治理已经进入“收口期”。
- 前端仍可见 `legacy compat` 逻辑，如 `src/stores/lifecycle.ts`、`src/api/positionLifecycleService.ts`。
- 后端仍存在 legacy / compat 暴露，如 `app/routers/quant_loop.py` 的 deprecated 自动执行入口、`app/routers/autonomy.py` 中的 `LEGACY_COMPAT` / `LEGACY_NONE` 语义。
- 当前页面和接口已经不缺“能力”，真正缺的是：**主路径、归属感、一致性、层次感、可维护性**。

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

V11.1.1 的成功不以“又加了多少页”来衡量，而以以下指标衡量：

- 页面收敛后，用户处理核心问题的平均点击路径显著缩短；
- 关键工作台的“结果 + 解释 + 来源 + 建议动作”口径统一；
- 前端活跃业务视图数明显下降，但能力不减少；
- 后端新增能力不再以“再加一个 router/service 文件”作为默认落地方式；
- Legacy compat 层开始可计划地下线，而不是永久累积。

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

### 2.2 交易经理视角：需要的是统一决策面，而不是更多图表

交易经理最关心的是：

- 当前资本是否被合理分配；
- 当前风险预算是否被低效占用；
- 当前哪些策略/执行/治理节点正在拖累收益；
- 当前是否存在必须人工介入的异常。

V11.1.1 对应要求：

- 每个核心工作台必须提供 **headline summary + blocker list + suggested action** 三段结构；
- 所有重大结论必须标明：**来源类型 / 数据质量 / 最后更新时间 / 推荐动作**；
- 所有治理结论必须能下钻到证据链，而不是只给状态颜色。

### 2.3 交易员视角：需要的是快、准、稳、少打断

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

V11.1.1 优先治理以下高价值重叠：

- `system-monitor` + `task-management` → 单页多 Tab
- `positions` + `position-evaluation` → 单工作台双视角
- `dashboard` + `war-room` → 统一 shell、统一过滤、统一摘要卡
- `order-book` + `execution-policy` + `trade-lifecycle` → 统一对象 ID、统一联动面包屑
- `autonomy` + 已经被 redirect 的历史入口（如 `ai-advisor` / `plans` / `execution-center`）→ 正式完成语义收口

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

- [ ] 前端活跃业务视图从当前 53 个基线明显收敛，目标 **≤ 40**
- [ ] redirect-only 历史别名路由显著减少，目标 **≤ 10**
- [ ] 核心问题均有唯一主入口，避免一类问题分散在多个平行页面
- [ ] 关键工作台全部具备统一的 explainability strip
- [ ] `system-monitor` 与 `task-management` 完成结构收口，不再长期并行为两个独立心智模型

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

#### 1. Bounded Contexts Inside `app/services`

后端继续保留 `app/services` 作为主目录，但不再无限平铺；V11.1.1 按上下文治理为子域：

- `autonomy`
- `research`
- `portfolio`
- `execution`
- `governance`
- `observability`
- `platform`（scheduler / config / health / integrations）

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
- legacy `quant_loop` 旁路需要进入 sunset 计划；
- 新功能不得再新增第二套决策/执行入口。

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

### Stage A — Inventory & Decision Records

- 页面归属矩阵定稿
- legacy alias / compat 清单定稿
- bounded context 划分定稿
- 关键工作台 read model 清单定稿
- ADR（Architecture Decision Record）开始落库

### Stage B — Frontend Workbench Convergence

- 收敛高价值重叠页面
- 引入 shared workbench shell
- 完成重点页面的统一状态机和 explainability strip
- 清理部分 legacy 路由与 UI 层 compat

### Stage C — Backend Query & Domain Refactor

- 引入核心工作台 read models
- 收敛 router/application/domain/adapters 分层
- 清理 legacy orchestration 旁路
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
