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

## 使用原则

- 当你关心“模块怎么分层”，看总体架构。
- 当你关心“数据怎么流转”，看核心数据流。
- 当你关心“为什么被拦截或降级”，看风控与治理。
- 当你关心“任务何时运行、谁驱动谁”，看任务编排。
- 当你关心“为什么资金闲置、哪里被卡住、有哪些自动改进候选”，看 V11.0.1 专题设计。