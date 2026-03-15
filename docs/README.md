# 后端文档导航

本目录汇总 AI Trading Backend V8 的权威设计与运行文档。

## 核心主文档

- [PRODUCT.md](PRODUCT.md) - 产品需求与版本规划
- [API.md](API.md) - API 参考与接口口径
- [BACKEND_DESIGN.md](BACKEND_DESIGN.md) - 后端总体设计
- [architecture/v11_2_1_rbac_workbench_design.md](architecture/v11_2_1_rbac_workbench_design.md) - V11.2.1 当前实现 & 生产基线（RBAC & Role Workbench）
- [architecture/v11_1_1_implementation_design.md](architecture/v11_1_1_implementation_design.md) - V11.1.1 已上线实现设计（Workbench convergence / read models / shared shell）
- [architecture/v11_0_1_implementation_design.md](architecture/v11_0_1_implementation_design.md) - V11.0.1 已上线实现设计（Capital Velocity / Self-Perception / Improvement Lab）
- [architecture/v11_3_1_multi_account_design.md](architecture/v11_3_1_multi_account_design.md) - V11.3.1 规划设计（Multi-Account Support & Account-Scoped Data Governance）

## 架构与核心能力专题

- [architecture/README.md](architecture/README.md) - 架构专题导航
- [architecture/system-architecture.md](architecture/system-architecture.md) - 系统上下文图、组件图、控制平面总览
- [architecture/signal-trade-position-flows.md](architecture/signal-trade-position-flows.md) - 信号、交易、持仓全链路时序与状态流
- [architecture/risk-and-governance.md](architecture/risk-and-governance.md) - 风控分层、防线机制、治理与放量纪律
- [architecture/job-orchestration.md](architecture/job-orchestration.md) - Scheduler、周期任务、后台编排与运维要点
- [architecture/v11_2_1_rbac_workbench_design.md](architecture/v11_2_1_rbac_workbench_design.md) - V11.2.1 当前实现 & 生产基线（RBAC / Role Workbench / 权限鉴权层）
- [architecture/v11_1_1_implementation_design.md](architecture/v11_1_1_implementation_design.md) - V11.1.1 已上线（工作台收敛 / read model / 薄路由）
- [architecture/v11_0_1_implementation_design.md](architecture/v11_0_1_implementation_design.md) - V11.0.1 Capital Intelligence 与 Autonomous Evolution OS 实现细节
- [architecture/v11_3_1_multi_account_design.md](architecture/v11_3_1_multi_account_design.md) - V11.3.1 规划设计（Multi-Account Support & Account-Scoped Data Governance）

## 历史与归档

- [archived/](archived/) - 历史版本规划与旧设计记录
- [product/README.md](product/README.md) - 产品文档拆分索引

## 阅读顺序建议

1. 先看 [system-architecture.md](architecture/system-architecture.md)，建立系统边界与模块分层认知。
2. 再看 [signal-trade-position-flows.md](architecture/signal-trade-position-flows.md)，理解信号到持仓的主链数据流。
3. 接着看 [risk-and-governance.md](architecture/risk-and-governance.md)，理解为什么系统不会“见信号就执行”。
4. 最后看 [job-orchestration.md](architecture/job-orchestration.md)，理解后台任务、巡检、回补与持续治理机制。
5. 如果你在排查 RBAC 鉴权 / 角色工作台 / 权限门禁，先读 [v11_2_1_rbac_workbench_design.md](architecture/v11_2_1_rbac_workbench_design.md)。
6. 如果你在排查工作台收敛、read model 或统一壳层，补读 [v11_1_1_implementation_design.md](architecture/v11_1_1_implementation_design.md)。
7. 如果你在排查资金闲置、自感知画像或改进候选，补读 [v11_0_1_implementation_design.md](architecture/v11_0_1_implementation_design.md)。
8. 如果你在了解多账户架构规划，先读 [v11_3_1_multi_account_design.md](architecture/v11_3_1_multi_account_design.md)。

## 图表约定

- 本目录中的架构图、流程图、时序图统一使用 Mermaid，便于在 VS Code 与 GitHub 中直接预览。
- 图示优先反映当前实现对应的真实模块，必要时会标注 feature flag、rollout phase 和 fallback 语义。
- 涉及交易、风控、执行的图示默认以保守执行为前提，不表达“自动信号必然成交”的错误语义。
