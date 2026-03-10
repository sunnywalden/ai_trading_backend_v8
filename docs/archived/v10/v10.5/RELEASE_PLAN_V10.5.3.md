# V10.5.3 Release Plan — Profit Engine Upgrade

> AI量化交易闭环系统 — V10.5.3 规划说明  
> 文档版本：Draft v1.0 | 更新日期：2026-03-10  
> 当前状态：规划中  
> 当前已上线版本：V10.5.1  
> 前序规划参考：V10.5.2（组合席位竞争）  
> 核心命题：把 `Alpha Lab / Portfolio / Execution Policy / Governance` 从“观测与解释界面”升级为真正影响净收益的控制回路。

---

## 0. 版本定位

### 0.1 一句话定义

V10.5.3 是一次 **Profit Engine Upgrade**：

> 在不提高系统风险上限的前提下，提升扣除执行成本后的净收益质量，并减少伪 alpha、低价值席位占用和无效换手。

### 0.2 为什么是 V10.5.3，而不是继续横向扩功能

如果用顶级量化平台的标准审视当前系统，平台已经明显具备以下基础：

1. 自主决策、风控、执行、复盘链路完整。
2. 生命周期、Order Book、War Room、Execution Microscope 等可观测性能力扎实。
3. 风险降低优先路径、SignalQualityFunnel、Ghost Trade、Model Degradation Guard 等机制已经把系统从“策略工具”推向“交易操作系统”。

但若目标是持续提升收益质量，当前平台最大的短板不是“功能还不够多”，而是以下四件事还不够硬：

1. **Alpha 真相口径仍偏观察层**：研究视图已经很丰富，但还没有完全把 gross alpha、net alpha、after cost、after turnover 区分成统一事实口径。
2. **资本分配仍偏约束驱动**：Risk Gate 很强，但组合还没有彻底转向按边际净收益分配风险预算。
3. **Execution Policy 仍偏解释层**：执行策略控制台已上线，但尚未全面反向驱动下单执行逻辑。
4. **Research→Live 治理仍偏看板**：策略晋级、回滚、证据链、shadow/live 对照仍需更强硬门槛。

因此 V10.5.3 的关键命题不是再做更多页面，而是：

> 把已经存在的研究、组合、执行、治理能力，变成真正能提高净收益的控制器。

---

## 1. 版本目标

### 1.1 北极星目标

让系统从“会看、会解释、会保护自己”进一步升级为：

- 会识别 **真实净 alpha**
- 会把资本优先分配给 **边际收益最高** 的对象
- 会在执行前估计并约束 **真实交易成本**
- 会用制度化的 evidence chain 决定 **什么可以上线、什么必须回滚**

### 1.2 北极星指标

| 指标 | 含义 | V10.5.3 目标 |
|------|------|--------------|
| Net Alpha Positive Rate | 扣除执行与换手成本后仍为正的策略占比 | 提升 |
| Seat Efficiency | 前 N 个席位贡献的净收益占比 | 提升 |
| Shadow-to-Live Consistency | Shadow / Paper / Live 的收益偏差 | 下降 |
| Average Realized IS | 实际执行短缺成本 | 下降 |
| Budget Breach Rate | 执行预算超限占比 | 下降 |
| Governance Evidence Coverage | 进入 Production 的策略具备完整证据链比例 | 100% |

---

## 2. 版本主线

## M1. Alpha Truth Engine 2.0

### 目标

建立统一且可审计的 alpha 真相口径，解决“看起来赚钱”与“净成本后赚钱”之间的落差。

### 核心能力

#### 1. Strategy Truth Snapshot

为每个策略、子策略、信号维度输出统一真相快照：

- gross return
- net return
- after slippage return
- after turnover penalty return
- hit rate
- payoff ratio
- average holding period
- regime-segmented performance
- capacity bucket performance
- signal decay truth

#### 2. Data Quality Hard Labels

所有研究和表现数据必须显式标记质量等级：

- `REAL`
- `INSUFFICIENT`
- `STALE`
- `PROXY`

平台不再用平滑代理值掩盖真实样本不足。

#### 3. Signal Decay Truth View

将 Signal Intelligence 中的 decay、IC、halflife 与真实成交后的收益绑定，输出：

- recent vs previous regime decay
- confidence bucket decay
- holding-period decay
- expected vs realized alpha gap

#### 4. Shadow Book Compare 2.0

对以下三类被拒对象建立影子账本：

- rejected by quality funnel
- rejected by risk gate
- rejected by execution / cost budget

核心指标：

- false reject rate
- protection benefit
- missed alpha after cost

### 交付结果

- `Alpha Lab` 不再只是研究汇总页，而是平台唯一的 alpha 真相工作台。
- 所有策略上线评估必须优先引用 net alpha，而非 gross alpha。

---

## M2. Portfolio Construction 2.1

### 目标

把组合构建从“满足风险约束”升级为“在风险约束内最大化边际净收益”。

### 核心能力

#### 1. Seat Value Model

为每个持仓与新信号计算统一席位价值：

$$
SeatValue = ExpectedNetAlpha - CostPenalty - CrowdingPenalty - CorrelationPenalty - LiquidityPenalty
$$

#### 2. CapacityArbiter 升级

`capacity_arbiter.py` 从“统一 admission score 排序”升级为“统一 seat value 排序”，并记录：

- 为什么换这个席位
- 为什么保留旧仓
- 替换后净收益提升是否覆盖摩擦成本

#### 3. Risk Budget Tree

新增分层风险预算：

- portfolio budget
- single-name budget
- sector budget
- factor budget
- event risk budget
- liquidity budget

#### 4. Marginal Contribution Dashboard

对每个候选持仓输出：

- marginal alpha
- marginal VaR
- marginal ES
- marginal turnover
- liquidity usage

### 交付结果

- 组合在满仓时不再只是“谁先来谁占位”，而是“谁最值得占用风险预算”。
- `Portfolio` 页面成为资金分配控制台，而不是单纯优化结果展示页。

---

## M3. Execution Policy Closed Loop

### 目标

让执行策略真正反向驱动下单，而不只是提供事后解释。

### 核心能力

#### 1. Pre-Trade Cost Model 接管执行前决策

每笔订单在提交前都要估计：

- spread cost
- delay cost
- market impact
- opportunity cost
- timing cost
- total expected cost

并以此约束是否执行、怎么执行、是否缩量执行。

#### 2. Unified Execution Policy Object

每笔订单统一输出执行策略对象：

- urgency
- algo_type
- max_participation_rate
- slippage_budget_bps
- child_order_interval_seconds
- cancel_replace_policy
- limit_offset_policy
- closing_override_policy

#### 3. OrderExecutor 接收真实执行策略参数

`order_executor.py` 不再仅按订单规模粗略选算法，而要消费 execution policy snapshot。

#### 4. Post-Trade Replay & Feedback

执行结果通过 `Execution Microscope` 回写到执行策略层，用于：

- symbol bucket quality
- urgency bucket quality
- algo bucket quality
- budget breach statistics

### 交付结果

- 执行层从“算法路由器”升级为“执行纪律系统”。
- 执行页看到的策略、预算与实际下单参数保持一致。

---

## M4. Research-to-Live Governance Hard Gate

### 目标

让策略晋级、放量、回滚变成制度化治理，而不是经验判断。

### 核心能力

#### 1. 五阶段晋级流水线

- Discovery
- Paper
- Shadow Live
- Challenger
- Production

#### 2. Evidence Chain

每个阶段都必须有证据对象：

- backtest evidence
- paper evidence
- shadow evidence
- execution evidence
- calibration evidence
- degradation / rollback risk

#### 3. Promotion / Rollback Hard Gates

晋级或回滚必须以硬门槛驱动，例如：

- sample count
- net alpha
- max drawdown
- turnover budget
- execution cost budget
- regime stability
- data quality

#### 4. Experiment Ledger Integration

ABTest 和实验结论不再停留在观察层，而是成为 promotion pipeline 的正式输入。

### 交付结果

- 没有证据链的策略不能进入 Production。
- 退化策略能够获得清晰的 rollback recommendation。

---

## 3. 前端规划要点

V10.5.3 的前端设计原则不是继续扩页，而是把已有页面升级成利润控制面：

1. **Alpha Lab** → 从研究看板升级为 Alpha Truth Engine 2.0
2. **Portfolio** → 从优化结果页升级为 Portfolio Construction 2.1 Console
3. **Execution Policy** → 从执行说明页升级为执行控制台
4. **Governance Pipeline** → 从阶段列表升级为硬门槛证据板

设计要求：

- 所有关键结论同时显示 **结果值 + 解释 + 数据质量**
- 页面优先强调 `why now / why size / why not larger / why not live`
- 继续坚持“决策级可视化而不是页面膨胀”

---

## 4. 后端实施重点

### Alpha Truth

- `v1051_research_service.py` 扩展为统一 truth snapshot 输出
- `signal_intelligence_service.py` 真值化 decay 与 IC 口径
- `backtest/runner.py` 输出 gross/net/cost-adjusted 结果

### Portfolio

- `capacity_arbiter.py` 升级为 seat value based arbiter
- `risk_gate_service.py` 接入 risk budget tree / liquidity budget 约束
- `trade_attribution_engine.py` 反哺 seat value 与 governance 证据

### Execution

- `execution_policy_service.py` 输出真实 policy 对象
- `order_executor.py` 消费 policy snapshot
- `execution_microscope_service.py` 回写执行反馈数据

### Governance

- 新增 promotion / evidence / rollback 相关 service
- `governance.py` 扩展为阶段明细、证据、阻塞原因接口

---

## 5. 版本优先级

### P0（必须完成）

1. Alpha Truth Engine 2.0
2. Seat Value + Portfolio Construction 2.1
3. Execution Policy Closed Loop
4. Governance Hard Gate

### P1（强烈建议完成）

1. Shadow compare 深化
2. Model degradation 与 governance 关联
3. Execution feedback bucketization

### P2（延后项）

1. 更多策略种类扩展
2. 更多 UI 变体与移动端增强
3. 非关键的新独立页面

---

## 6. 统一验收标准

### 6.1 Alpha Truth

- [ ] 每个策略可同时查看 gross / net / after cost / after turnover 四种口径
- [ ] 所有研究卡片带 `data_quality` 字段
- [ ] Shadow Book 可输出 false reject rate 与 protection benefit

### 6.2 Portfolio Construction

- [ ] 满仓时可解释“为什么换这个，不换那个”
- [ ] 组合建议显示 marginal alpha / risk / turnover / liquidity usage
- [ ] 风险预算树可解释任何 scaled-down 决策

### 6.3 Execution Policy

- [ ] 每笔订单都生成 pre-trade cost estimate 与 policy snapshot
- [ ] 实际执行参数与执行页展示一致
- [ ] 平均 realized IS 与 budget breach 指标可持续跟踪

### 6.4 Governance

- [ ] Production 策略 100% 具备证据链
- [ ] 退化策略可见 rollback blockers / rollback reason
- [ ] 无证据或样本不足的策略不能默认进入 live

---

## 7. 发布策略建议

### Stage A — Observe

- 新逻辑仅计算，不改变 live 控制路径

### Stage B — Shadow Control

- 在 shadow / paper 中启用新的 truth / seat value / execution control 逻辑

### Stage C — Semi Rollout

- 在 `SEMI` 模式下有限接管

### Stage D — Full Control

- 作为默认控制链路进入 FULL

建议 feature flags：

- `ALPHA_TRUTH_V2_ENABLED`
- `SEAT_VALUE_ARBITER_ENABLED`
- `EXECUTION_POLICY_HARD_CONTROL_ENABLED`
- `GOVERNANCE_HARD_GATE_ENABLED`

---

## 8. 最终判断

V10.5.3 的价值不在于继续增加功能总量，而在于把已有系统能力变成净收益控制回路。

如果 V10.4.x 解决的是“系统能否稳定自主运行”，V10.5.1 解决的是“系统是否具备机构级研究与治理框架”，那么 V10.5.3 解决的问题是：

> 这套系统是否真的能把资本、执行与上线权，持续分配给最值得拥有它们的 alpha。
