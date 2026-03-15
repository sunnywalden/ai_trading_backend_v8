# 架构专题导航

本目录面向后端研发、联调、运维与治理，集中描述系统最重要的运行机制。

## 文档清单

### 1. 总体架构

- [system-architecture.md](system-architecture.md)

包含：

- 系统上下文图
- 后端核心组件图
- 控制平面与数据平面的职责分离
- 路由层、服务层、引擎层、任务层与数据源的对应关系

### 2. 核心数据流

- [signal-trade-position-flows.md](signal-trade-position-flows.md)

包含：

- 信号发现到自动执行的主时序图
- 持仓监控触发强制退出的时序图
- 交易后流水线 S12-S16 流程图
- 关键状态与真源说明

### 3. 风控与治理

- [risk-and-governance.md](risk-and-governance.md)

包含：

- 分层风控机制图
- 质量漏斗、容量仲裁、RiskGate、Circuit Breaker 的职责边界
- 体制、审计、治理放量与 feature flags

### 4. 任务编排

- [job-orchestration.md](job-orchestration.md)

包含：

- FastAPI 启动阶段任务注册图
- APScheduler 任务分组与执行节奏
- 闭环任务、观测任务、数据任务、修复任务的边界
- 运维与排障建议

### 5. V11.0.1 专题

- [v11_0_1_implementation_design.md](v11_0_1_implementation_design.md)

包含：

- Capital Velocity / Self-Perception / Improvement Lab 的实现优先级
- 新增服务、数据模型、feature flags
- 当前已上线 autonomy 端点与反馈回路

### 6. V11.1.1 专题（已上线）

- [v11_1_1_implementation_design.md](v11_1_1_implementation_design.md)

包含：

- Trader Workbench Convergence 实现文档
- WorkbenchShell / ExplainabilityStrip / read model 设计
- workbench 端点列表与 feature flag 策略

### 7. V11.2.1 RBAC & Role Workbench 专题（已上线，当前生产基线）

- [v11_2_1_rbac_workbench_design.md](v11_2_1_rbac_workbench_design.md)

包含：

- 六张 RBAC 核心表设计（roles / permissions / users / user_role_bindings / role_permission_grants / authorization_audit_logs）
- JWT payload 扩展与 `/api/v1/auth/me` feature_flags 口径
- `require_permission()` / `require_any_role()` FastAPI 依赖注入设计
- 四类角色工作台首页（Researcher / Trader / Supervisor / Administrator）
- 路由可见范围矩阵与后端路由守卫设计
- feature flags 分类与 Admin API 设计

### 8. LLM 原生量化平台设计提案

- [llm-native-quant-os.md](llm-native-quant-os.md)

包含：

- 当前“控制平面主导 + 局部 LLM 增强”架构与目标范式的差距
- LLM-native Quant OS 的目标分层、认知内核与确定性边界
- 自我模型 / 世界模型 / 反思 / 自诊断 / 自主研究循环的落地建议
- 基于当前仓库结构的渐进式演进路线，而非推倒重来

## 使用原则

- 当你关心“模块怎么分层”，看总体架构。
- 当你关心“数据怎么流转”，看核心数据流。
- 当你关心“为什么被拦截或降级”，看风控与治理。
- 当你关心“任务何时运行、谁驱动谁”，看任务编排。
- 当你关心“为什么资金闲置、哪里被卡住、有哪些自动改进候选”，看 V11.0.1 专题设计。
- 当你关心“如何从当前平台演进到大模型原生量化平台”，看 LLM 原生量化平台设计提案。
- 当你在排查 RBAC 权限、角色工作台或路由守卫，看 V11.2.1 RBAC & Role Workbench 专题。
- 当你在了解多账户规划或 BrokerAccountRegistry 设计，看 [v11_3_1_multi_account_design.md](v11_3_1_multi_account_design.md)（V11.3.1 规划，未上线）。
