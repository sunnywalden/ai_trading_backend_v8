# V11.1.1 Implementation Design — Trader Workbench Convergence & Architecture Simplification

> 状态：当前代码实现  
> 更新日期：2026-03-15  
> 生产基线：V11.0.1（已上线）

---

## 1. 版本定位

V11.1.1 当前实现不是继续横向扩页，也不是重做交易主链，而是把已经存在的核心能力收敛成更清晰、更可解释、更易维护的工作台体系。

本轮实现聚焦三件事：

1. **统一工作台壳层**：让关键页面共享一致的标题区、摘要区、状态语言与解释条。
2. **引入工作台聚合读模型**：让前端消费稳定的 read model，而不是在多个页面重复拼装数据。
3. **压实工程约束**：保持 thin router、typed contract、public service API 与单主编排路径纪律。

---

## 2. 当前实现边界

### 2.1 已落地范围

- 前端：
  - `src/views/DashboardV2Page.vue`
  - `src/views/IntelligentOrderBookPage.vue`
  - `src/views/SystemMonitorPage.vue`
- 共享组件：
  - `src/components/workbench/WorkbenchShell.vue`
  - `src/components/workbench/ExplainabilityStrip.vue`
- 路由收口：
  - `/task-management` 复用 `SystemMonitorPage.vue`
  - 通过 `tab=tasks` 与路径识别进入任务管理视图
- 后端聚合读模型：
  - `app/services/read_models/dashboard_summary.py`
  - `app/services/read_models/order_book_workbench.py`
  - `app/services/read_models/system_monitor_workbench.py`
- 后端接口：
  - `GET /api/v1/dashboard/v2/workbench-summary`
  - `GET /api/v1/order-book/workbench`
  - `GET /api/v1/system-monitor/workbench`

### 2.2 明确不做的事

- 不改动 `AutonomousEngine.run_decision_cycle()` 作为自动交易唯一主编排入口的地位。
- 不放宽 RiskGate、容量纪律、治理硬门或 rollout discipline。
- 不新增平行 Dashboard / Control Plane / Monitor 体系。
- 不为了“统一 UI”而把研究、执行、治理语义混成单一超大页面。

---

## 3. 前端设计

### 3.1 Shared workbench shell

三个主工作台统一接入 `WorkbenchShell`，负责承载：

- 页面标题与副标题
- 最近更新时间
- 数据质量标签
- degraded / stale / loading 状态
- summary cards 区域
- header actions 区域

这样做的目的，是让工作台具备统一的页面语法，而不是每个页面各写一套 header + summary + loading/error 骨架。

### 3.2 Explainability strip

三个主工作台统一接入 `ExplainabilityStrip`，默认展示：

- 结果值（result value）
- 解释文本（explanation）
- 来源类型（source type）
- 数据质量（data quality）
- 最近更新时间（last updated）
- 建议动作（suggested action）

这让“结论 + 原因 + 下一步动作”在工作台层成为默认能力，而不是依赖页面作者临时发挥。

### 3.3 Task convergence

`/task-management` 不再维护独立页面逻辑，而是复用 `SystemMonitorPage.vue`，在路由级保持直达能力，在工作台级统一收口到 tasks Tab。

收益：

- 避免并行维护两套监控 / 任务 header 与刷新逻辑
- 让“系统监控”和“任务运行状态”共享同一工作台语境
- 保留历史入口，避免外链或书签失效

### 3.4 Typed workbench contract

前端为工作台聚合接口建立 typed contract：

- Dashboard：`DashboardWorkbenchSummaryResponse`
- System Monitor：`SystemMonitorWorkbenchResponse`
- Order Book：继续基于聚合 summary 做 explainability 消费

这意味着页面不再直接假设后端“顺手返回什么字段都能吃”，而是通过更稳定的 DTO 面向工作台开发。

---

## 4. 后端设计

### 4.1 Read model first

V11.1.1 当前实现把工作台聚合逻辑显式放入 `app/services/read_models/`：

- read model 只做查询聚合
- 不承载写入或编排副作用
- 目标是降低前端多请求拼装成本

这类接口不是交易主链的一部分，而是工作台视图层的查询适配层。

### 4.2 Thin router discipline

新增 workbench 路由遵循：

- router 负责 request / response / auth / parameter validation
- 复杂聚合下沉到 read model service
- 404 等显式失败场景在 route metadata 中声明
- 参数风格遵循 `Annotated + Query/Depends`

### 4.3 Public service API instead of protected helpers

为避免 read model 直接调用 `DashboardV2Service` 的私有方法，当前实现新增 public workbench context：

- `DashboardV2Service.get_capital_velocity_context(account_id)`

这样可以保持：

- service 内部私有 helper 仍可继续重构
- read model 只依赖稳定公共契约
- 类型检查和架构边界更清晰

### 4.4 Single orchestration path remains intact

当前实现没有引入第二条自动交易编排路径。

工作台 read model 只是“看板读模型”，不会参与：

- 信号生成
- 风险放行
- 自动执行
- 治理晋级

因此它不会破坏 V10.5.4 / V11.0.1 已建立的控制平面纪律。

---

## 5. 为什么当前实现满足 A-D

### A. 架构设计清晰，具有前瞻性

- 前端通过 `WorkbenchShell` 与 `ExplainabilityStrip` 建立统一工作台骨架。
- 后端通过 `read_models/` 建立查询聚合层，降低页面与业务服务的直接耦合。
- 单主编排路径继续由 `AutonomousEngine.run_decision_cycle()` 持有，避免平行控制面。

### B. 算法、功能实现优雅且高性能

- System Monitor workbench 统一刷新 API 报告与 provider stats，减少重复请求。
- Order Book summary 复用 workbench 读模型，不再维护重复聚合逻辑。
- Dashboard workbench 把 capital velocity 解释链收口成单次聚合读取。

### C. 高复用、低复杂度、可读性高

- 三个主工作台共享壳层与解释条。
- task-management 复用系统监控页面，而不是继续并行演进。
- read model 使用 public service API，而不是跨层读取 protected helper。
- 新增 FastAPI 路由风格、响应声明与类型约束更统一。

### D. 符合最佳实践原则

- 合理区分“当前代码实现”和“生产已上线基线”。
- router / read model / service 分工更明确。
- typed contract 代替弱约束对象拼装。
- UI 状态语言与 explainability 走共享组件，而不是复制粘贴。

---

## 6. 当前接口与页面对照

| 工作台 | 前端页面 | 聚合接口 | 说明 |
| --- | --- | --- | --- |
| Command Center | `/dashboard` | `/api/v1/dashboard/v2/workbench-summary` | 聚合账户摘要 + capital velocity explainability |
| Execution & Lifecycle | `/order-book` | `/api/v1/order-book/workbench` | 聚合订单簿摘要与工作台解释上下文 |
| Governance & Operations | `/system-monitor` | `/api/v1/system-monitor/workbench` | 聚合 API 监控报告与 provider stats |
| Governance & Operations | `/task-management` | 复用 `/system-monitor` | 通过 tasks Tab 收口，不再维护平行页面逻辑 |

---

## 7. 后续增量建议

当前实现已经满足 V11.1.1 的首批治理目标；后续如果继续推进，建议按以下顺序扩展：

1. 把更多 workbench 页纳入统一 shell（如 `/portfolio`、`/autonomy`）
2. 为更多主工作台补齐 read model 与 DTO 契约层
3. 继续清理 legacy route / compat 判断
4. 为关键 read model 补充 contract test 与更明确的性能预算

---

## 8. 结论

V11.1.1 当前实现的核心价值，不是“又多了几个功能”，而是：

- 让主工作台开始有统一的结构语言；
- 让前后端开始围绕稳定的 read model / contract 协作；
- 让代码在继续演进时更不容易滑回“页面多点拼装、后端继续平铺”的旧路径。

这意味着当前实现已经满足本轮版本对 **架构清晰、实现优雅、高复用低复杂度、符合最佳实践** 的要求。
