# V10.5.4 Release Plan — Signal Pipeline Integrity & Control-Plane Hardening

> AI量化交易闭环系统 — V10.5.4 规划说明  
> 文档版本：Draft v1.0 | 更新日期：2026-03-11  
> 当前状态：规划中  
> 当前已上线版本：V10.5.2  
> 上一轮规划参考：V10.5.3 Profit Engine Upgrade  
> 核心命题：在继续推进收益控制回路前，先把信号发现、状态真源、执行主链、审计口径与治理流程收敛成可验证、可放量、可回退的统一控制平面。

---

## 0. 版本定位

### 0.1 一句话定义

V10.5.4 是一次 **Signal Pipeline Integrity & Control-Plane Hardening**：

> 先解决“信号是真是假、状态以谁为准、执行到底走哪条链、审计到底来自哪里”这四个系统性问题，再把 Profit Engine 的高级能力接入真实控制面。

### 0.2 为什么从 V10.5.3 演进到 V10.5.4

V10.5.3 已经明确了利润控制回路的大方向：

- Alpha Truth Engine 2.0
- Portfolio Construction 2.1
- Execution Policy Closed Loop
- Governance Hard Gate

但在落地过程中暴露出一个更底层的问题：**控制回路本身的输入、状态与执行语义仍不够收敛**。如果不先解决这些基础一致性问题，继续推进 Seat Value、Pre-Trade Cost、Governance Hard Gate，只会把更复杂的逻辑叠加到仍然分裂的底座上。

因此 V10.5.4 的目标不是否定 V10.5.3，而是把它真正落地所依赖的“控制平面”补齐：

1. **信号发现真实性**：区分 REAL / SYNTHETIC / BACKFILL，避免把模拟信号和真实 alpha 混在一起。
2. **信号 payload 真源统一**：停止在 `factor_scores / extra_metadata / signal_dimensions` 间多点写入、运行时拼装。
3. **自动执行主链统一**：明确 `AutonomousEngine.run_decision_cycle()` 是唯一自动执行编排入口。
4. **状态机与审计原生化**：不再依赖 fallback 推断解释交易行为，而是写原生 transition / audit / evidence。
5. **控制面渐进放量**：所有硬接管能力都必须经 `Observe → Shadow → Semi → Full` 四阶段治理。

---

## 1. 版本目标

### 1.1 北极星目标

让系统从“后处理能力很强，但输入与状态真源仍有裂缝”，升级为：

- 会识别 **真实信号 vs 合成信号**
- 会基于 **统一 payload** 进行质量、风控与执行决策
- 会通过 **唯一自动执行主链** 执行交易
- 会用 **原生状态迁移与原生审计** 解释每个信号的命运
- 会在接管真实链路前完成 **可验证的 rollout 治理**

### 1.2 北极星指标

| 指标 | 含义 | V10.5.4 目标 |
| ------ | ------ | -------------- |
| Real Signal Coverage | 自动执行候选中带 `signal_origin_mode=REAL` 的占比 | 明确可观测，成为默认主集 |
| Canonical Payload Coverage | 新信号使用统一 payload 的占比 | 100% |
| Native Audit Coverage | Watchtower / Pipeline 优先使用原生审计而非 fallback 的比例 | ≥ 90% |
| Status Drift Rate | 信号状态与执行/审计视图不一致比例 | 显著下降 |
| Execution Path Consistency | 自动执行实际通过 AutonomousEngine 编排的比例 | 100% |
| Rollout Safety Coverage | 新控制能力具备 flag + phase + rollback 的覆盖率 | 100% |

---

## 2. 版本主线

## M1. Signal Discovery Integrity

### M1 目标

把“真实交易信号”和“样本/模拟/回填信号”彻底分开，避免发掘层污染利润控制回路。

### M1 核心能力

#### 1. Signal Origin Mode

所有信号统一标记：

- `REAL`
- `SYNTHETIC`
- `BACKFILL`

`TradingSignal`、研究卡片、Watchtower、Alpha Lab、诊断面板都必须可见该标签。

#### 2. Synthetic Isolation

- `strategy_jobs.py` 的 `_sample_assets()`、mock dimensions、回放型样本不得再伪装成真实信号。
- 自动执行主链默认只消费 `REAL`；`SYNTHETIC` 只允许在 Observe / Demo / Test 路径使用。

#### 3. Discovery Quality Visibility

建立 discovery 质量指标：

- real vs synthetic count
- synthetic leakage into execution
- missing resonance metadata count
- stale generated signal count

### M1 交付结果

- 平台终于能回答“这个信号到底是真是假”。
- Profit Engine 的上层控制逻辑不再建立在混合信号池之上。

---

## M2. Canonical Signal Payload & State Machine

### M2 目标

建立信号唯一真源，结束多点写入、多处 fallback 和状态漂移。

### M2 核心能力

#### 1. Canonical Signal Payload

建立统一 payload（建议版本化）：

- `signal_payload.version`
- `signal_payload.origin`
- `signal_payload.dimensions`
- `signal_payload.resonance`
- `signal_payload.quality_inputs`
- `signal_payload.execution_hints`

新信号必须只写这一份 canonical payload；旧字段仅做兼容读取。

#### 2. Native State Transition Log

建立统一状态迁移系统：

- `from_status`
- `to_status`
- `actor`
- `reason_code`
- `reason_detail`
- `correlation_id`
- `created_at`

禁止到处直接修改 `signal.status` 而不留下 transition 记录。

#### 3. Recovery Semantics

加入控制面恢复能力：

- `QUEUED` 超时回收
- `EXECUTING` 超时触发 broker sync / rescue
- `VALIDATED but displacement pending` 明确状态化，而不是隐式停留

### M2 交付结果

- 信号质量评估、风控、执行看到的是同一个 payload。
- 任何“为什么这个信号没执行 / 被拒 / 卡住”都能从原生 transition log 回答。

---

## M3. Autonomous Control Plane Hardening

### M3 目标

把 `AutonomousEngine` 变成真正唯一的自动执行控制平面，并把 capacity / risk / governance 统合进来。

### M3 核心能力

#### 1. Single Auto-Execution Entry

明确：

- `AutonomousEngine.run_decision_cycle()` = 唯一自动执行编排入口
- `OrderExecutor` = broker adapter
- `SignalEngine.validate_signal()` = 轻量预校验 / 工具入口，不代表最终准入
- `/execute-signals` = legacy/manual path，默认不用于生产自动化

#### 2. Unified Runtime Truth Sources

统一以下真源：

- active positions source
- regime source
- execution path source
- audit source

建议优先级：

- positions：Position / lifecycle 真源
- regime：Redis runtime > DB latest snapshot > conservative fallback
- execution：AutonomousEngine intent / policy snapshot
- audit：native logs first, reconstructed fallback second

#### 3. Capacity Displacement Closure

把席位竞争从“打标记”升级为完整编排：

- displacement pending state
- exit submitted state
- exit filled → wake waiting entry
- shadow / dry-run / rollback metrics

### M3 交付结果

- 平台对“自动执行到底怎么被编排”的回答变得唯一且可审计。
- CapacityArbiter、RiskGate、Execution Policy 不再各讲各的故事。

---

## M4. Native Audit, Governance & Rollout Discipline

### M4 目标

让 Watchtower、Governance 和发布流程成为真正的制度化控制器，而不是事后解释层。

### M4 核心能力

#### 1. Native Audit First

每个关键阶段写原生审计：

- generation
- validation
- quality funnel
- risk gate
- capacity decision
- execution intent
- broker result
- lifecycle close

前端必须显式区分：

- `NATIVE_AUDIT`
- `RECONSTRUCTED`

#### 2. Governance Hardening

将 V10.5.3 的 `Discovery / Paper / Shadow Live / Challenger / Production` 五阶段接入真实控制面：

- evidence chain required
- sample count threshold
- data quality threshold
- execution quality threshold
- rollback blockers / downgrade suggestion

#### 3. Complete Development Workflow

V10.5.4 必须按完整开发流程推进，不允许只写计划不收口：

1. 文档对齐：`PRODUCT / BACKEND_DESIGN / API / FRONTEND_DESIGN`
2. 后端真源与状态机落地
3. 前端工作台升级与原生审计展示
4. 单元测试 / 集成测试 / E2E / 产品验收
5. Observe → Shadow → Semi → Full 渐进放量

### M4 交付结果

- Watchtower 从“猜测解释器”升级为“原生审计视图”。
- 发布过程本身变成治理对象，而不是口头流程。

---

## 3. 完整开发流程（V10.5.4 定稿）

### 第 1 阶段：文档对齐

- `PRODUCT.md / FRONTEND_DESIGN.md / BACKEND_DESIGN.md / API.md` 统一到 `V10.5.4`
- 明确：版本定位、feature flags、rollout phases、验收矩阵、legacy 路径、真实主链
- 定义 canonical payload 草案与状态机事件字典

### 第 2 阶段：后端阻塞项

优先完成：

1. `signal_origin_mode` 全链路接入
2. canonical signal payload 统一
3. native signal transition log
4. AutonomousEngine 单主链收敛
5. positions / regime / audit 真源统一
6. capacity displacement 完整闭环

### 第 3 阶段：前端工作台升级

仅升级现有工作台，不扩页：

- `/alpha-lab`
- `/portfolio`
- `/execution-policy`
- `/governance/pipeline`
- `/autonomy` / Watchtower

新要求：所有关键结论必须同时显示：

- 结果值
- 解释字段
- 数据质量
- 来源类型（native/reconstructed）
- signal_origin_mode

### 第 4 阶段：测试与联调

必须完成：

- 单元测试
- 集成测试
- front-back API 联调
- Cypress / Vitest 端到端验证
- 回归检查 legacy path 不误接管生产逻辑

### 第 5 阶段：渐进放量

| 阶段 | 目标 | 规则 |
| ------ | ------ | ------ |
| Observe | 只观测，不接管 | 计算 canonical / native audit / truth sources，但不改 live 行为 |
| Shadow | 影子接管 | 新控制平面仅在 shadow / paper 路径运行，记录与旧链差异 |
| Semi | 半接管 | 对有限真实链路启用 canonical payload / unified control plane，保留人工回退 |
| Full | 全接管 | AutonomousEngine + native audit + governance hard gate 成为默认主链 |

---

## 4. Feature Flags（V10.5.4 定稿）

- `SIGNAL_PIPELINE_V1054_ENABLED`：控制 canonical payload / origin mode / native transition log 是否进入主链
- `AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED`：控制单主链收敛、legacy path 限制、统一执行编排是否接管
- `NATIVE_AUDIT_V1054_ENABLED`：控制 Watchtower / signal pipeline 是否优先使用原生审计
- `GOVERNANCE_HARD_GATE_ENABLED`：延续 V10.5.3，控制五阶段治理是否参与真实放量
- `SEAT_VALUE_ARBITER_ENABLED`：延续 V10.5.3，用于在控制平面收敛后切换 SeatValue 仲裁
- `EXECUTION_POLICY_HARD_CONTROL_ENABLED`：延续 V10.5.3，用于在执行主链统一后接入 pre-trade cost hard control

---

## 5. 统一验收标准

### 5.1 Signal Discovery Integrity

- [ ] 自动信号全部带 `signal_origin_mode`
- [ ] `SYNTHETIC` 信号默认不进入生产自动执行主链
- [ ] discovery 诊断面可观测 real vs synthetic 分布

### 5.2 Canonical Payload & State Machine

- [ ] 新信号 100% 写 canonical payload
- [ ] Watchtower / Quality Funnel / CapacityArbiter / AutonomousEngine 优先读取 canonical payload
- [ ] 原生状态流转可完整回答任一信号为何被拒、为何执行、为何卡住

### 5.3 Autonomous Control Plane

- [ ] 自动执行 100% 由 `AutonomousEngine.run_decision_cycle()` 编排
- [ ] positions / regime / audit 真源在 UI 与执行链中一致
- [ ] displacement pending → exit submitted → exit filled → entry released 可完整回放

### 5.4 Native Audit & Governance

- [ ] Watchtower 默认优先显示 native audit，fallback 明确标记 `RECONSTRUCTED`
- [ ] 关键控制能力全部具备 flag + phase + rollback 能力
- [ ] `Discovery → Production` 的治理证据链可对接真实控制平面

### 5.5 测试与发布

- [ ] 单元测试、集成测试、前后端联调与产品验收全部通过
- [ ] Observe / Shadow / Semi / Full 四阶段的切换策略经过演练
- [ ] 任何 `V10.5.4` 新控制逻辑都可以在 feature flag 层快速回退

---

## 6. 最终判断

V10.5.4 的价值不在于再继续“加一层高级收益控制概念”，而在于先把平台变成：

> 一个拥有统一信号真源、统一状态机、统一自动执行主链、统一原生审计视图的可治理交易控制平面。

只有在这个底座收敛之后，V10.5.3 里规划的 Alpha Truth / Seat Value / Execution Policy / Governance Hard Gate，才会真正变成可靠的利润控制回路，而不是建立在语义分裂之上的复杂逻辑。
