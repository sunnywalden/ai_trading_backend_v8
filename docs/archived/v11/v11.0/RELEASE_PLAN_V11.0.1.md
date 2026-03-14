# V11.0.1 Release Plan — Success-Rate First Capital Velocity & Autonomous Evolution OS

> AI量化交易闭环系统 — V11.0.1 规划说明  
> 文档版本：Draft v1.1 | 初稿日期：2026-03-13 | 最后审查：2026-03-14  
> 当前状态：规划提案（已对当前实现做对齐校核，见各节"已有基础"与第 7 节数据迁移要求）  
> 当前规划基线：V10.5.4 Signal Pipeline Integrity & Control-Plane Hardening  
> 代码核查版本：`v1051_research_service.py`、`capacity_arbiter.py`、`insight_service.py`（含 ABTestEngine）、`weekly_report_service.py`  
> 核心命题：**在不牺牲成功率、不放宽风险上限的前提下，提高资金轮转效率，最大化净收益，并让系统具备自我感知、自我提升、自我进化能力，升级为新一代顶尖个人量化交易系统。**

---

## 0. 版本定位

### 0.1 一句话定义

V11.0.1 是一次 **Success-Rate First Capital Velocity & Autonomous Evolution OS** 升级：

> 让平台不只是“能交易、会风控、可观测”，而是能围绕**成功率优先的资金轮转**做实时资本编排，并基于自身表现、环境变化和执行反馈，持续完成**自我感知 → 自我诊断 → 自我优化 → 自我进化**。

### 0.2 V10.5.4 实测诊断：大量资金闲置的具体成因

> 以下诊断结合 V10.5.4 模拟盘实际运行截图与 `/api/v1/signal-pipeline` 接口真实响应数据（2026-03-14），是 V11.0.1 设计的核心驱动依据。

#### 诊断现象

| 现象 | 实测数据 | 严重程度 |
|------|---------|---------|
| 现金闲置 | 总资产 $905K，预估现金 $298K（占比 ~33%），最大购买力 $247万未使用 | 🔴 高 |
| 近命中信号反复被拒 | ORCL ENTRY `conviction_score=92`，阈值 93（BULL_TREND），每小时触发一次均被 Layer 4 拒绝；同时 `gross_exposure_allocator.reason="no-headroom", target_qty=0`（**双重阻断**） | 🔴 高 |
| 亏损仓位无法减仓 | ACDC AI评分 50/100（建议 REDUCE），REDUCE 信号被 PositionRebalanceMonitor 生成后仍遭拒绝，持仓亏损 -9.36% | 🔴 高 |
| 资金配置效率失衡 | 5 个仓位合计市值 $606K，未实现亏损 $8136，持仓分布不均（AMD 单仓 $313K，占比 >50%） | 🟡 中 |

#### API 接口字段还原（ORCL 信号 `3be3b87f-4d05-4381-befb-76ac32d59a55`）

下表从 `/api/v1/signal-pipeline?limit=30` 响应中提取关键字段，供 V11 实现者精确对照：

| 字段 | 值 | 含义 |
|------|-----|------|
| `signal_quality_score` | `92` | Layer 4 置信度分值 |
| `signal_quality_tier` | `"MEDIUM"` | 低于 HIGH 门槛（95），tier 在 conviction 之后计算 |
| `funnel_rejected_at_layer` | `4` | 被第 4 层（置信度校准门）拒绝 |
| `funnel_rejection_reason` | `"LOW_CONVICTION"` | 拒绝原因枚举 |
| `rejection_stage` | `"QUALITY_FUNNEL"` | 拒绝阶段 |
| `rejection_detail` | `"Conviction Score 92.0 < 阈值 93 (composite=98.0, resonance_bonus=90, regime_alignment=100)"` | composite / resonance / regime 三项均优秀，唯 conviction 差 1 分 |
| `gross_exposure_allocator.capped` | `true` | GEA 也触发上限裁剪 |
| `gross_exposure_allocator.reason` | `"no-headroom"` | **第二阻断点**：敞口上限已满，`target_qty` 被置 0 |
| `gross_exposure_allocator.target_qty` | `0` | 即使 Layer 4 通过，执行层仍无可分配仓位 |
| `signal_quality_quota_exempt` | `false` | MEDIUM 级信号不享日配额豁免 |
| `quantity` | `0.2442` | 请求仓位 24.42% 净值（~$221K） |

#### 根因分析

**根因 1：置信度阈值摩擦（Conviction Threshold Friction）**

- 代码路径：`signal_quality_config.py` 的 `_REGIME_OVERRIDES["BULL_TREND"]["conviction_threshold"] = 93`
- ORCL `conviction_score = 92`，`composite_score = 98`，`resonance_bonus = 90`，`regime_alignment = 100`——其他全优，唯 conviction 差 1 分
- Layer 4 硬拒绝，系统无近命中感知；每轮消耗信号算力、API 配额、DB 写入，资金零部署

**根因 2：信号质量 Tier 死锁（Tier Classification Lock）**

- `signal_quality_tier = "MEDIUM"` 是因为 `conviction_score 92 < HIGH_QUALITY_SIGNAL_SCORE = 95`
- Tier 是 conviction 的**下游计算结果**：`conviction 不足 → tier ≤ MEDIUM → 不满足 tier 豁免条件`
- 任何"用 tier 判断是否启用阈值软化"的机制均存在**逻辑死锁**：软化需要 tier≥HIGH，但 tier≥HIGH 需要 conviction 已达标，而 conviction 未达标正是需要软化的原因
- 正确门控应使用 **conviction 上游的独立维度**（`composite_score` / `resonance_bonus`），见 M1.5 修正

**根因 3：GrossExposureAllocator 双重阻断（GEA No-Headroom with Idle Cash）**

- 代码路径：`gross_exposure_allocator.py` 第 271 行 `if remaining_cap_pct <= 0 or max_additional_symbol_pct <= 0:` → `reason="no-headroom", target_qty=0`
- 执行链路：`_ai_decide()` 调用 `gross_exposure_allocator.allocate_entry()` → GEA 结果存入 `decision["gross_exposure_allocator"]` → 存入 watchtower metadata（CONTROL_PLANE 阶段）
- 即使 Layer 4 软化通过，执行层 `qty = target_qty = 0` → AutonomousEngine 判定为 `HOLD/no-op` → 信号 SKIPPED
- ORCL 是**两个独立阻断点同时触发**，仅修复 Layer 4 不够，GEA 层也必须处理
- 核心矛盾：持仓市值 $606K / 净值 $905K = 66.7% 总敞口，但账户有 $298K 现金，GEA `no-headroom` 说明运行时计算敞口已触及配置上限——闲置现金未被 GEA 识别为"可用空间"

**根因 4：亏损持仓虚假持有（False Hold in Deteriorating Position）**

- 代码路径：`position_rebalance_monitor.py` `_SCORE_REDUCE_THRESHOLD = 54`，ACDC 评分 50 ≤ 54，已生成 REDUCE 信号
- REDUCE 信号在信号质量漏斗/执行层被二次阻断，但 `rejection_stage` 原因未穿透到持仓层告警
- 结果：-9.36% 亏损持仓长期占位，消耗风险预算，锁定可轮转资本

**根因 5：系统无"闲置成本"概念（No Idle Capital Cost Awareness）**

- GEA 敞口判断、Layer 4 阈值、CVS 排序：闲置资金的机会成本权重均为零
- 系统不会因为"目前资金大量闲置"主动降低准入门槛或调整 GEA headroom

#### 对 V11.0.1 的设计约束

以下问题必须在 V11.0.1 的 M1 / M2 设计中得到可量化解答：

1. **「连续 N 次近命中阈值」** → 需要 Conviction Friction Tracker（见 M1.5.1）
2. **「$298K 现金闲置却 GEA no-headroom」** → 需要 GEA Idle-Capital-Aware Check（见 M1.5.3）
3. **「tier 不能作为软化门控」** → 改用 `composite_score` + `resonance_bonus` 独立维度（见 M1.5.2 修正）
4. **「REDUCE 信号被下游阻断原因未穿透」** → 需要 False-Hold Alert + REDUCE/EXIT bypass（见 M2.3）
5. **「全系统闲置资本代价为零权重」** → 需要 Idle Capital Pressure 进入 CVS（见 M1.1）

---

### 0.3 为什么是 V11.0.1

如果说：

- **V10.5.3** 解决的是“利润控制回路”的方向问题；
- **V10.5.4** 解决的是“信号、状态、执行、审计真源统一”的底座问题；

那么 **V11.0.1** 要解决的问题是：

> 当控制平面已经统一之后，系统是否能够像一名顶尖职业交易员 + 交易总监 + 研究主管一样，持续识别哪里该重仓、哪里该快进快出、哪里该慢、哪里该停，并把资金、注意力和风险预算，自动分配给当前最值得拥有它们的机会。

这不是简单“加更多功能”，而是把平台从“机构级交易操作系统”进一步升级为：

1. **成功率优先的资本调度系统**：不是为了高换手而高换手，而是在高胜率、高净值效率场景下提升资金轮转。
2. **有自我认知的交易系统**：知道自己当前擅长什么、不擅长什么、哪里退化、哪里拥挤、哪里浪费了资金占用。
3. **会持续提升的交易系统**：能把失败、错过、滑点、持有过久、加减仓错误等问题沉淀成结构化改进动作。
4. **会受治理地进化的交易系统**：策略、参数、仓位模板、执行策略、市场优先级都能在证据链约束下自动演进。

---

## 1. 版本目标

### 1.1 北极星目标

围绕“**保证成功率前提下，提高资金轮转，最大化收益**”这一目标，V11.0.1 的北极星定义为：

- 更快识别**高把握度**机会；
- 更快释放被低效占用的资金与风险预算；
- 更快把资本轮转到**单位时间净收益更高**的机会；
- 更早感知策略、模型、执行、市场状态的退化；
- 更稳地在真实反馈中完成自我修正与版本级进化。

### 1.2 核心设计原则

| 原则 | 含义 | V11.0.1 解释 |
| ---- | ---- | ------------ |
| 成功率优先 | 所有轮转与提速必须建立在成功率、净 alpha、执行可达性基础上 | 不接受“高换手换来低质量收益” |
| 净收益优先 | 关注扣除滑点、冲击、拥挤、持有成本后的真实收益 | 不是看 gross return，而是看 unit-time net return |
| 资本占用敏感 | 任何仓位都必须回答“你占用这份资本是否值得” | 引入资本占用半衰期与席位再评估 |
| 系统自感知 | 系统必须知道自己当前是否健康、有效、退化、失真 | 自感知不是监控页，而是决策输入 |
| 进化受治理 | 任何自优化、自学习、自升级都必须可回放、可回退、可审计 | 不允许“黑箱自进化”直接接管实盘 |

### 1.3 北极星指标

| 指标 | 含义 | V11.0.1 目标方向 |
| ---- | ---- | ---------------- |
| Capital Velocity Efficiency | 单位风险预算在单位时间内创造的净收益效率 | 提升 |
| Success-Adjusted Turnover | 仅统计高质量成功交易后的有效轮转率 | 提升 |
| Net Return per Risk Minute | 每单位风险占用分钟创造的净收益 | 提升 |
| Idle Capital Ratio | 因低效持仓、等待、卡滞造成的无效资金占比 | 下降 |
| False Hold Rate | 本应减仓/换仓/退出却继续占位的比例 | 下降 |
| Self-Diagnosis Coverage | 可被系统自动解释和归因的问题覆盖率 | ≥ 90% |
| Improvement Loop Cycle Time | 从发现问题到形成优化动作上线 shadow 的时间 | 显著缩短 |
| Evolution Safety Coverage | 自优化/自进化动作具备 evidence + flag + rollback 的覆盖率 | 100% |

---

## 2. 版本主线

## M1. Success-Rate First Capital Velocity Engine

### M1 目标

把“资金轮转”从一个结果指标，升级为一个被系统主动优化的核心控制对象。
> **已有基础（不需从零建）**  
> `capacity_arbiter.py` 已实现 V10.5.2 席位竞争仲裁（`CapacityArbiterService`），含准入分排序、保护带、冷却期、单周期最大替换数；`execution_policy_service.py` 已有 `seat_value` 评估逻辑；`trade_attribution_engine.py` 已追踪成交成本。  
> **新增 / 扩展**：在 `CapacityCandidate` 基础上引入 `capital_velocity_score` 字段；为持仓增加 `alpha_half_life_minutes` 属性；Turnover Guardrails 以现有 `MIN_REPLACEMENT_EDGE` 等参数为基础扩展。
### M1 核心能力

#### 1. Capital Velocity Score（CVS）

为每个持仓、候选信号、待替换席位计算统一的资金轮转价值分数：

$$
CVS = WinProb \times ExpectedNetAlpha \times FillConfidence \times TimeEfficiency - RiskPenalty - FrictionPenalty - CrowdingPenalty
$$

其中：

- `WinProb`：成功率 / 命中率置信估计
- `ExpectedNetAlpha`：扣除预计执行成本、换手惩罚、体制折扣后的预期净 alpha
- `FillConfidence`：当前流动性与执行可达性评分
- `TimeEfficiency`：单位持有时间的收益效率（避免“慢收益占用快资金”）
- `RiskPenalty`：风险预算消耗、相关性、尾部暴露惩罚
- `FrictionPenalty`：滑点、市场冲击、换仓摩擦成本
- `CrowdingPenalty`：拥挤交易与共振衰减惩罚

#### 2. Capital Occupancy Half-Life

每个仓位新增“资本占用半衰期”概念，回答：

- 这个仓位的 alpha 是否正在衰减？
- 它继续占用资金是否仍优于新机会？
- 它处于“该持有、该减仓、该退出、该换仓”的哪个区间？

#### 3. Seat Rotation 2.0

在 V10.5.2 席位竞争基础上，升级为“成功率修正 + 时间效率修正”的席位轮转系统：

- 不仅比较谁的 `seat_value` 更高
- 还比较谁的**单位风险分钟净收益更高**
- 输出：
  - 为什么继续持有
  - 为什么减少占用
  - 为什么提前释放
  - 为什么等待更优 entry

#### 4. Turnover Guardrails

所有提速行为必须受四类约束：

- success floor（成功率下限）
- net alpha floor（净收益下限）
- friction ceiling（摩擦成本上限）
- replacement discipline（替换纪律）

系统禁止通过“更频繁但质量更差”的方式伪造高轮转。
#### 5. Conviction Threshold Friction Relief（置信度阈值摩擦缓释）

> **V10.5.4 实测驱动**：ORCL ENTRY 置信度 92 连续多小时被 BULL_TREND 阈值 93 拒绝，$298K 现金持续闲置。

解决当前系统"近命中信号反复被拒 + 资金闲置无感知"双盲问题：

**5.1 Conviction Friction Tracker（置信度摩擦追踪器）**

- 记录每个 symbol/方向 近 N 个周期内的置信度分布（conviction rolling window）
- 判定是否处于"阈值摩擦状态"：连续 ≥ M 次，置信度在 `[threshold - Δ, threshold)` 区间（建议 Δ=3, M=3）
- 摩擦状态记入 `meta_state_snapshot`，在信号管道视图与 War Room 中可见

**5.2 Idle-Capital-Aware Threshold Softening（闲置资本感知型阈值软化）**

> ⚠️ **设计修正（来自接口实测数据）**：`signal_quality_tier` 是 `conviction_score` 的**下游计算结果**，不能作为软化触发的前置条件，否则存在**逻辑死锁**（需要软化才能升 tier，升 tier 才能软化）。  
> 实测：ORCL `tier = "MEDIUM"`，是因为 `conviction_score 92 < HIGH_QUALITY_SIGNAL_SCORE 95`；而 `composite_score = 98`、`resonance_bonus = 90` 均是 conviction 的**上游独立维度**，不受 conviction 值影响。  
> **正确门控：使用 `composite_score` + `resonance_bonus` 而非 `signal_quality_tier`。**

同时满足以下四个条件时，允许对 Layer 4 置信度阈值应用有界松弛（`CONVICTION_THRESHOLD_SOFT_FLOOR`）：

| 条件 | 说明 | 建议默认值 | ORCL 实测值 |
|------|------|----------|------------|
| 当前 `idle_cash_ratio` | 现金 / 总资产 > 门槛 | `> 25%` | ~33% ✅ |
| 近命中持续周期 | conviction 在阈值 `-Δ` 以内连续被拒次数 ≥ N | `Δ=3, N=3` | 持续多轮 ✅ |
| `composite_score`（**独立维度**，非 tier） | 多维融合分，与 conviction_score 计算路径独立 | `≥ 96` | `98.0` ✅ |
| `resonance_bonus`（**独立维度**，非 tier） | 共振加成，与 conviction_score 计算路径独立 | `≥ 80` | `90` ✅ |

满足条件时，有效阈值 = `max(CONVICTION_THRESHOLD_SOFT_FLOOR, threshold - soft_relief)`，其中：
- `CONVICTION_THRESHOLD_SOFT_FLOOR`：绝对下界，不可再低（建议 88 for BULL_TREND）
- `soft_relief`：松弛幅度上限（建议 ≤ 3 分）
- 松弛行为必须写入审计日志，并在信号 Pipeline 视图标注 `[SOFT_THRESHOLD]` 标签

**安全围栏**：
- 仅对 ENTRY / ADD 信号适用，REDUCE / EXIT 不参与此机制
- `CAPITAL_VELOCITY_V1101_ENABLED = False` 时此机制完全关闭
- 单周期内被松弛通过的信号数量不超过 `max_soft_relief_per_cycle`（建议 = 1）
- **不使用 `signal_quality_tier` 作为条件**（tier 为 conviction 下游，循环依赖）

**5.3 GrossExposureAllocator Idle-Capital-Aware Check（GEA 闲置资本感知修正）**

> **新增（来自接口实测数据）**：ORCL 信号同时被 Layer 4 AND GEA `no-headroom` 两重阻断。即使 Layer 4 软化通过，`target_qty = 0` 仍会导致信号在 AutonomousEngine 被判 SKIPPED（`qty=0 → no-op`）。必须同步解决 GEA 层。
>
> 代码路径：`gross_exposure_allocator.py` 第 271 行：`if remaining_cap_pct <= 0 or max_additional_symbol_pct <= 0: return ... reason="no-headroom", target_qty=0`

当以下条件**同时成立**时，GEA 应进入"闲置资本感知模式"，重新核算 `remaining_cap_pct`：
- `gross_exposure_allocator.reason = "no-headroom"`（触发当前路径）
- `idle_cash_ratio > IDLE_CAPITAL_ALERT_THRESHOLD`（显著现金闲置，非真正满仓）
- 请求仓位 `base_position_pct ≤ idle_cash_ratio × IDLE_CAPITAL_GEA_HEADROOM_FACTOR`（本次开仓可由现金直接覆盖）

行为：
- 满足以上条件时，将 `effective_max_gross_pct` 临时上调至 `current_gross_pct + min(idle_cash_ratio, 0.30)`（最多借用 30% 净值空间），重跑分配逻辑
- 仅影响 `target_qty` 计算，不修改全局风险上限，不绕过 RiskGate 其他检查
- 结果写入 `gross_exposure_allocator.idle_capital_adjusted = true`，原始 `no-headroom` 原因保留在 `original_reason` 字段
- `CAPITAL_VELOCITY_V1101_ENABLED = False` 时此逻辑完全关闭，GEA 行为保持 V10 不变

**5.4 Idle Capital Pressure 进入 CVS 计算**

在 CVS 公式中增加 `+ IdleCapitalBonus` 项：

$$
CVS = WinProb \times ExpectedNetAlpha \times FillConfidence \times TimeEfficiency - RiskPenalty - FrictionPenalty - CrowdingPenalty + IdleCapitalBonus
$$

- `IdleCapitalBonus = idle_cash_ratio \times capital_idle_opportunity_cost_weight`，仅当 `idle_cash_ratio > IDLE_CAPITAL_ALERT_THRESHOLD` 时激活
- 含义：当现金大量闲置时，入场动作本身具备额外的"让资金工作"价值
- 在 CVS 解释字段中须单独列出 `idle_capital_bonus` 贡献，让决策可追溯
### M1 交付结果

- 平台能够回答“为什么这笔资金现在应该继续留在这里 / 应该转去别处”。
- 轮转提效建立在成功率优先前提上，而不是牺牲胜率换速度。

---

## M2. Self-Perception Nervous System（自我感知神经系统）

### M2 目标

让平台具备对自身状态、市场状态、策略状态、执行状态、资本利用状态的持续感知能力，并把这种感知直接输入决策回路。

> **已有基础（不需从零建）**  
> - `autonomy_health_monitor.py`：自主健康检查  
> - `model_degradation_monitor_service.py`：模型置信退化检测  
> - `signal_intelligence_service.py`：信号观测  
> - `execution_microscope_service.py`：执行成本与成交质量  
> - `situational_awareness_service.py`：态势感知快照（`SituationalAwarenessSnapshot`）  
>
> **新增 / 扩展**：在 `situational_awareness_service.py` 基础上扩展为 `MetaStateSnapshot`（含 Capital / Model 状态，需新建 DB 表，见第 7 节）；Self-Awareness Alerts 作为新告警类别接入 `smart_alert_service.py`；Counterfactual 标签已部分在 `decision_post_mortem_service.py` 实现（`counterfactual_buy/hold/sell`），可扩展为入场 / 退出滑动标签。

### M2 核心能力

#### 1. System Self-Perception Graph

建立统一自感知图谱，覆盖五类状态：

- **Market State**：当前市场体制、波动、流动性、热点密度、事件压强
- **Strategy State**：各策略当前胜率、衰减、拥挤度、适配体制、信号新鲜度
- **Execution State**：成交质量、预算超限、fill risk、延迟、冲击成本
- **Capital State**：资金利用率、风险预算占用、低效仓位、等待资本、轮转堵点
- **Model State**：模型置信度、校准偏差、异常漂移、推理稳定性、降级状态

#### 2. Meta-State Snapshot

为每次决策周期生成系统级元状态快照：

- 当前最强 alpha 来源是什么
- 当前最大的收益阻塞是什么
- 当前最大的失败风险是什么
- 当前最浪费资金的区域是什么
- 当前最值得加速轮转的市场/策略/账户是什么

#### 3. Self-Awareness Alerts

新增自感知告警，不仅提示系统故障，还提示“交易系统自身的行为问题”：

- 低效占位预警
- 胜率退化预警
- 过度等待预警
- 过度交易预警
- 执行成本失真预警
- 拥挤共振失效预警
- 参数过拟合风险预警
**False-Hold Alert（虚假持有告警）**

> **V10.5.4 实测驱动**：ACDC 仓位 AI 评分 50/100（低于 `_SCORE_REDUCE_THRESHOLD = 54`），`PositionRebalanceMonitor` 已生成 REDUCE 信号，但信号被质量漏斗或执行层二次阻断，`rejection_stage`/`rejection_reason` 未穿透到持仓层，导致 -9.36% 亏损持仓持续占位，锁定可轮转资本。

触发条件：某持仓对应的 REDUCE / EXIT 信号连续 ≥ K 个周期（建议 K=3）被质量漏斗或执行层拒绝，且拒绝原因非 `MARKET_CLOSED` / `COOLDOWN`。

告警内容（写入 `meta_state_snapshot.false_hold_alerts`）：
- `symbol`、`position_id`、`current_score`（如 ACDC=50）
- REDUCE/EXIT 信号 ID、`rejection_stage`、`rejection_reason`、已被拒次数
- 当前浮亏金额与浮亏百分比
- 建议动作：人工确认减仓 / 触发 REDUCE 信号 fast-path bypass
- `/autonomy` 页面展示，不静默消耗

**REDUCE/EXIT Fast-Path Bypass（受保护通道）**：
- 当且仅当持仓满足 False-Hold 触发条件，且 AI 综合评分 ≤ `_SCORE_REDUCE_THRESHOLD` 时，REDUCE/EXIT 信号可跳过 Layer 4 置信度校准门（但仍须通过 Layer 1/2/3 及 RiskGate）
- bypass 行为通过 `signal_bypass_reason = "FALSE_HOLD_PROTECTION"` 字段记录在信号审计日志中
- `CAPITAL_VELOCITY_V1101_ENABLED = False` 时此 bypass 完全关闭，不影响现有漏斗逻辑
#### 4. Counterfactual Self-Reflection

每次关键决策都生成轻量反事实标签：

- 如果更快退出，结果会不会更好？
- 如果更晚入场，成功率是否更高？
- 如果仓位更小/更大，风险收益比是否更优？
- 如果不轮转，是否更优？

### M2 交付结果

- 系统从“看市场”升级为“同时看市场和自己”。
- 自感知结果不只是展示层，而会进入 `Portfolio / Risk / Execution / Governance` 的真实控制逻辑。

---

## M3. Self-Improvement Engine（自我提升引擎）

### M3 目标

让系统不仅知道哪里做得不好，还能自动形成带优先级的改进动作，并在 shadow / paper 环境验证后逐步进入主链。

> **已有基础（不需从零建）**  
> - `insight_service.py`：`InsightService`（洞察 CRUD）、`WeeklyInsightGenerator`（周度 AI 洞察）、`ABTestEngine`（A/B 实验，含 `create_experiment / evaluate_experiment / list_experiments`）  
> - `decision_post_mortem_service.py`：事后剖析，含三路 counterfactual  
> - `weekly_report_service.py`：`WeeklyReportService`，生成周复盘文本  
> - `trade_attribution_engine.py`：成交成本与收益归因  
>
> **新增 / 扩展**：`WeeklyInsightGenerator` 扩展为结构化三段（保留 / 停止 / 尝试）Weekly Learning Pack 输出；Improvement Backlog 新增 `ImprovementCandidate` 数据模型持久化候选列表（见第 7 节数据模型）。

### M3 核心能力

#### 1. Bottleneck Attribution Engine

对收益损失、轮转不畅和成功率下降做结构化归因，形成统一问题分类：

- alpha 不足
- 入场太早 / 太晚
- 持有太久
- 退出太慢
- 仓位过大 / 过小
- 执行成本过高
- 替换过慢
- 风险预算占用不合理
- 体制错配
- 模型置信度失真

#### 2. Improvement Backlog Auto-Generation

系统自动生成改进待办，不再只靠人工总结：

- 规则候选（Rule Candidate）
- 参数调整候选（Parameter Candidate）
- 仓位模板候选（Sizing Candidate）
- 执行策略候选（Execution Candidate）
- 晋级/降级建议（Promotion / Demotion Candidate）

每条候选都必须附带：

- 问题证据
- 预期收益改善
- 影响范围
- 风险说明
- 验证方式

#### 3. Improvement Lab

新增 Improvement Lab 工作台，统一管理：

- 问题榜单（Top draggers）
- 机会榜单（Top upgrade opportunities）
- 试验状态（Observe / Shadow / Challenger / Adopt / Rollback）
- 实验结果（成功率、净收益、轮转效率、回撤影响）

#### 4. Weekly Learning Pack

每周自动生成系统学习包，沉淀：

- 过去 7 天最值得保留的行为
- 最应停止的行为
- 最值得加速验证的改进动作
- 下周轮转重点方向
- 下周限制交易方向

### M3 交付结果

- “复盘”从被动总结升级为主动改进流水线。
- 平台会给出“下一步该怎么变得更好”，而不是只展示“之前发生了什么”。

---

## M4. Self-Evolution Governance（自我进化治理）

### M4 目标

让策略、参数、权重、执行模板、轮转纪律可以在证据链和风控边界内受治理地自动进化。

> **已有基础（不需从零建）**  
> - `v1051_research_service.py`：完整治理管道快照（`get_governance_pipeline_snapshot`）、晋级 / 回滚建议（`_build_rollback_suggestion`）、证据链构建（`_build_governance_evidence`）；当前运行状态集：`DISCOVERY / PAPER / SHADOW_LIVE / CHALLENGER / PRODUCTION`  
> - `paper_trading_service.py`：模拟盘毕业评估与晋级建议  
> - `governance.py` 路由：`GET /api/v1/governance/pipeline`  
>
> **新增 / 扩展**：`StrategyGenome` 数据模型（见第 7 节）；`LIMITED` / `RETIRED` 新状态枚举（见下方映射表）；自动晋级 / 回滚触发器。

### M4 核心能力

#### 1. Strategy Genome & Evolution Ledger

为每个策略维护“进化谱系”：

- 当前版本
- 参数基因
- 适用体制
- 胜率分布
- 衰减速度
- 执行适配度
- 资本效率
- 升级 / 回滚历史

#### 2. Promotion / Demotion / Retirement Engine

策略、参数、执行模板进入统一演化状态机：

- `DISCOVERY`
- `PAPER`（纸面测试 / 回测阶段）
- `SHADOW_LIVE`（影子实盘）
- `CHALLENGER`
- `PRODUCTION`（主链运行，即原方案中的 `ADOPTED`）
- `LIMITED`  ← **V11 新增**，受限上线（仅适用特定策略 / 市场 / 账户）
- `RETIRED`  ← **V11 新增**，已退役，不再参与任何排序与分配

> **与当前代码状态机的对齐说明**
>
> | V11 规划名称 | 代码实际名称 | 对齐策略 |
> |---|---|---|
> | `SHADOW` | `SHADOW_LIVE` | 文档统一改用 `SHADOW_LIVE`，**不做重命名**，避免全量历史数据迁移 |
> | `ADOPTED` | `PRODUCTION` | 文档统一改用 `PRODUCTION`，语义等价 |
> | `LIMITED` | *(不存在)* | **新增**枚举值，需 Alembic migration |
> | `RETIRED` | *(不存在)* | **新增**枚举值，需 Alembic migration |
> | `PAPER` | `PAPER` | 无变化 |
> | `DISCOVERY` | `DISCOVERY` | 无变化 |
>
> 回滚路径保持当前逻辑不变：  
> `PRODUCTION → CHALLENGER → SHADOW_LIVE → PAPER → DISCOVERY`

任何升级或降级必须由以下证据触发：

- 成功率稳定性
- 体制适配性
- 净收益改进
- 轮转效率改进
- 执行质量稳定性
- 风险预算一致性

#### 3. Personal Style Alignment

在不走黑箱个性化的前提下，引入“个人交易风格对齐层”：

- 对收益波动容忍度建模
- 对持有周期偏好建模
- 对回撤容忍度建模
- 对轮转节奏偏好建模

让系统进化方向更贴近“个人顶尖量化系统”的实际使用语境，而不是泛化到机构多人共识模式。

#### 4. Evolution Safety Ring

所有自进化动作必须具备：

- feature flag
- adoption threshold
- automatic rollback
- human review hook
- audit trail

### M4 交付结果

- 平台具备“持续演化”的能力，但不牺牲可控性。
- 自我进化不再是抽象愿景，而是有状态机、有证据链、有回滚纪律的真实系统能力。

---

## M5. Next-Gen Personal Quant Workbench（新一代个人量化讲评台）

### M5 目标

把前端工作台升级为真正的“讲评台 / 指挥台 / 进化台”三位一体中枢，让用户像管理一支顶尖交易团队一样管理自己的量化系统。

### M5 核心能力

#### 1. Capital Velocity Cockpit

新增或升级核心视图，统一展示：

- 当前资金占用地图
- 高质量轮转机会队列
- 低效席位清单
- 风险预算释放路径
- unit-time net return 排行
- “应快 / 应慢 / 应停”建议

#### 2. Self-Perception Board

集中展示系统当前自感知结论：

- 我现在最强的赚钱模式是什么
- 我现在最大的失误来源是什么
- 我现在最拥挤、最脆弱的区域是什么
- 我现在最应该收缩还是扩张
- 我现在最适合哪种执行节奏

#### 3. Improvement & Evolution Board

集中展示：

- 本周 Top 5 改进建议
- 当前 shadow 实验
- 晋级 / 回滚建议
- 已验证可采纳的规则候选
- 自进化动作的证据链与风险提示

#### 4. Copilot as CIO/COO

让 Copilot 不只是问答入口，而是担任：

- **CIO（Chief Investment Officer）**：解释当前资本分配逻辑、策略优先级、最强 alpha 区域
- **COO（Chief Operating Officer）**：解释当前系统运行瓶颈、执行质量、数据健康、轮转阻塞
- **Learning Coach**：解释最近系统学到了什么、下一步会尝试什么、为什么建议这样演进

### M5 交付结果

- 用户看到的不再是分散页面，而是一套真正围绕“赚钱能力 + 学习能力 + 演化能力”的顶尖个人量化操作台。
- 平台具备“讲得清、看得透、改得动、进得化”的完整工作台体验。

---

## 3. 前端规划要点

V11.0.1 的前端原则不是继续加页面，而是围绕“讲评台”升级现有核心工作台：

1. **`/alpha-lab`** (`AlphaLabPage.vue`) → Alpha Truth + Success-Adjusted Opportunity Console
2. **`/portfolio`** (`PortfolioPage.vue`) → Capital Velocity & Seat Rotation Console
3. **`/execution-policy`** (`ExecutionPolicyPage.vue`) → Fill Confidence & Cost Discipline Console
4. **`/governance/pipeline`** (`GovernancePipelinePage.vue`) → Improvement / Evolution Governance Board；新增 Improvement Lab 子标签页
5. **`/autonomy`** (`AutonomyPage.vue`) → Self-Perception & System Reflex Console（M2 自感知看板的主落点）
   - **注意**：`/signal-watchtower` (`SignalWatchtowerPage.vue`) 是 V10.4.2 已存在的独立路由（信号哨所），与 `/autonomy` 是两个独立入口，不合并。M2 自感知结论在 `/autonomy` 升级视图内展示；信号预算 / 信号异常仍在 `/signal-watchtower`。
6. **`/war-room`** (`WarRoomPage.vue`) → 从实时指挥视图升级为"资本轮转 + 系统自感知"总控台

统一设计要求：

- 所有关键结论同时显示：
  - 结果值
  - 解释字段
  - 数据质量
  - 置信度
  - 来源类型
  - 推荐动作
  - 证据链状态
- 所有“建议加速轮转”的结论必须同时显示“为什么不会伤害成功率”。
- 所有“建议改进 / 进化”的结论必须可下钻到证据与实验记录。

---

## 4. 后端实施重点

### 4.1 Capital Velocity

重点升级：

- `capacity_arbiter.py`
- `risk_gate_service.py`
- `execution_policy_service.py`
- `autonomous_engine.py`
- `trade_attribution_engine.py`
- `signal_quality_funnel.py`（M1.5.2 Layer 4 阈值软化入口）
- `signal_quality_config.py`（M1.5.2 `CONVICTION_THRESHOLD_SOFT_FLOOR` 与新配置项注册）
- `gross_exposure_allocator.py`（M1.5.3 闲置资本感知模式，`idle_capital_adjusted` 字段）

新增能力：

- capital velocity score
- capital occupancy half-life
- success-adjusted turnover metrics
- unit-time net return attribution
- conviction friction tracking（`meta_state_snapshot.throttled_signals`）
- GEA idle-capital-aware headroom recalculation

### 4.2 Self-Perception

重点升级：

- `signal_intelligence_service.py`
- `execution_microscope_service.py`
- `research_service / v1051_research_service.py`
- `autonomy health / system monitor` 相关服务

新增能力：

- meta-state snapshot
- self-awareness alerts
- counterfactual self-reflection tags
- capital blockage diagnostics

### 4.3 Self-Improvement

重点升级：

- `decision_post_mortem_service.py`
- `insight_service.py`（已含 `WeeklyInsightGenerator`、`ABTestEngine`，直接扩展）
- `weekly_report_service.py`（周报框架已存在，升级为结构化 Learning Pack 输出）
- `governance / pipeline` 相关 service

> ⚠️ **注意**：`ab_test_engine.py` 作为独立文件**不存在**于当前代码库。A/B 实验能力实现在 `insight_service.py` 的 `ABTestEngine` 类中（含 `create_experiment / evaluate_experiment / list_experiments`）。V11 实施应扩展该类，**而非新建同名文件**。

新增能力：

- bottleneck attribution engine（扩展 `trade_attribution_engine.py`）
- rule/parameter/sizing/execution candidates（新增 `ImprovementCandidate` 数据模型，见第 7 节）
- improvement backlog auto-generation（扩展 `WeeklyInsightGenerator`）
- weekly learning pack（升级 `WeeklyReportService`，输出结构化三段：保留 / 停止 / 尝试）

### 4.4 Self-Evolution

重点升级：

- governance pipeline
- strategy registry / experiment ledger
- promotion / rollback state machine

新增能力：

- strategy genome
- evolution ledger
- promotion / demotion / retirement engine
- style alignment constraints

---

## 5. Feature Flags（建议）

- `CAPITAL_VELOCITY_V1101_ENABLED`：控制 capital velocity score、capital occupancy half-life、轮转约束是否进入主链
- `SELF_PERCEPTION_V1101_ENABLED`：控制 meta-state snapshot、自感知告警、自反事实标签是否启用
- `IMPROVEMENT_ENGINE_V1101_ENABLED`：控制 bottleneck attribution、改进待办自动生成、Improvement Lab 是否启用
- `EVOLUTION_GOVERNANCE_V1101_ENABLED`：控制 strategy genome、演化状态机、晋级/回滚自动建议是否启用
- `STYLE_ALIGNMENT_V1101_ENABLED`：控制个性化交易风格约束是否参与排序、晋级和仓位模板生成

> **与现有控制平面的集成要求**
>
> 以上 5 个 flag 均须：
> 1. 在 `app/core/config.py` 的 `Settings` 类中注册（默认值 `False`，安全缺省），并在 `.env.example` 中增加对应注释
> 2. 在 `GET /api/v1/autonomy/status` 响应的 `flags` 字段中暴露（参照现有 `SIGNAL_PIPELINE_V1054_ENABLED` 模式，见 `app/routers/autonomy.py`），以便 Observe / Shadow 阶段在控制台可核验
> 3. 在 `GET /api/v1/execution-policy/overview` 控制状态中同步体现

---

## 6. 统一验收标准

### 6.1 Success-Rate First Capital Velocity

- [ ] 每个持仓 / 候选信号都可输出 `capital_velocity_score`
- [ ] 系统可解释“为什么这笔资本继续持有 / 应释放 / 应轮转”
- [ ] 所有轮转建议同时显示成功率影响、净收益影响与摩擦成本影响
- [ ] 资金轮转效率提升不以成功率显著下降为代价
- [ ] **V10.5.4 诊断验证**：`conviction_score ≥ (threshold - Δ)` 且 `composite_score ≥ 96` 且 `resonance_bonus ≥ 80` 且 `idle_cash_ratio > 25%` 且连续被拒 ≥ 3 次时，信号 Pipeline 视图中该信号条目出现 `[SOFT_THRESHOLD]` 标签，有效阈值可被观测到降低
- [ ] **V10.5.4 诊断验证**：当 `gross_exposure_allocator.reason = "no-headroom"` 且 `idle_cash_ratio > IDLE_CAPITAL_ALERT_THRESHOLD` 时，GEA 不再直接置 `target_qty=0`，而是重算并写 `idle_capital_adjusted=true`，确保信号不因 qty=0 被静默 SKIPPED
### 6.2 Self-Perception

- [ ] 每个决策周期可生成系统级 `meta-state snapshot`
- [ ] 系统可自动识别低效占位、成功率退化、执行成本失真、拥挤失效等问题
- [ ] 自感知结论已进入 Portfolio / Risk / Execution / Governance 的真实控制逻辑
- [ ] **V10.5.4 诊断验证**：ACDC 类的「REDUCE 信号反复被下游阻断」场景能自动触发 False-Hold Self-Awareness Alert，包含 `rejection_stage`、`rejection_reason`、已被拒次数、当前浮亏，在 `/autonomy` 页面可见
- [ ] **V10.5.4 诊断验证**：Conviction Friction Tracker 在近命中状态下，`meta_state_snapshot` 中包含 `throttled_signals` 列表，展示信号 ID、已被拒次数、当前 friction_gap（阈值 - conviction）、`composite_score`、`resonance_bonus`

### 6.3 Self-Improvement

- [ ] 系统能自动生成改进候选，并附带证据、预期收益与验证方案
- [ ] `Improvement Lab` 可追踪每个改进候选从发现到 shadow 的完整流程
- [ ] 周级学习包能输出“该保留什么 / 该停止什么 / 该尝试什么”

### 6.4 Self-Evolution

- [ ] 策略、参数、执行模板具备统一演化状态机与证据链
- [ ] 晋级、降级、退役建议可解释且支持回滚
- [ ] 所有自进化动作具备 feature flag、phase rollout 与审计记录
- [ ] `LIMITED` / `RETIRED` 新状态已通过 Alembic migration 写入 DB，历史策略记录无状态漂移
- [ ] 前端治理管道快照中每个 strategy 均显示新状态并展示对应说明

### 6.5 Workbench 体验

- [ ] 讲评台可同时回答“现在怎么赚钱、哪里在失分、接下来怎么改、为什么这样演化”
- [ ] 所有关键建议可下钻到数据、解释、证据和历史实验
- [ ] Copilot 可基于系统当前元状态提供 CIO / COO / Learning Coach 三类解释

---

## 7. 发布策略建议

### 前置：数据模型与迁移要求

以下变更须在进入任何 Stage **之前**完成，以防止历史数据与新实现语义不一致。

| 模型 / 变更 | 类型 | 说明 |
|---|---|---|
| `strategy.governance_stage` 枚举 | **扩展** | 增加 `LIMITED`、`RETIRED` 两个枚举值；Alembic migration；现有行无需修改 |
| `ImprovementCandidate` 新表 | **新建** | 持久化改进候选（type / evidence / expected_impact / status / reviewed_at）；M3 Improvement Lab 依赖此表 |
| `StrategyGenome` 新表 | **新建** | 持久化每个策略的参数快照与进化历史；与 `strategy.id` 1:N 关联 |
| `MetaStateSnapshot` 新表 | **新建** | 每个决策周期生成一条系统级元状态快照；需设 TTL 清理策略（建议保留 90 天） |
| `ai_insight` / `weekly_report` | **无结构变更** | `WeeklyReportService` 输出格式扩展为结构化三段 JSON，向后兼容旧文本字段 |

> 所有 migration 脚本须放在 `scripts/migrations/` 下，支持 dry-run 和回滚，在 Stage A 启动前完成。

### Stage A — Observe

- 完成数据模型迁移（见上方"前置"）
- 只计算 capital velocity、自感知、自提升候选与演化建议
- 不改变 live 执行行为
- 所有 V11 feature flags 注册至 `config.py` 并在 `/api/v1/autonomy/status` 可见，均设为 `false`
- 核心目标：验证指标与解释是否可信

### Stage B — Shadow Optimization

- 在 shadow / paper 中启用 capital rotation、improvement ranking、evolution suggestion
- 对比旧逻辑：
  - 成功率差异
  - 资金占用差异
  - 净收益差异
  - 执行成本差异

### Stage C — Semi Adoption

- 在有限真实账户 / 有限策略 / 有限市场启用 capital velocity 主链
- 自提升建议仍需人工确认或治理批准

### Stage D — Guided Evolution

- 允许有限类别的低风险优化动作自动进入主链
- 例如：执行参数微调、持有时长阈值微调、候选排序权重微调
- 仍保留硬回滚机制

### Stage E — Full Autonomous Evolution

- 在满足证据与安全覆盖条件后，允许平台对部分策略和执行模板进行受治理自动演化
- 仍不允许绕过风控和治理硬门槛

---

## 8. 非目标（明确边界）

V11.0.1 当前**不以**下列事项为主目标：

1. 单纯扩充更多页面数量
2. 盲目提升交易频率
3. 放宽 VaR / Stress / Position 限制换取收益
4. 在没有证据链的情况下自动修改核心风险参数
5. 先做多用户平台化而削弱“个人顶尖量化系统”这一主线

---

## 9. 最终判断

V11.0.1 的价值，不在于把系统做得更复杂，而在于把平台真正推进到一个更高等级：

> **它不仅会交易，还会感知自己；不仅会复盘，还会形成改进动作；不仅会优化参数，还会在治理框架内持续演化。**

如果 V10.5.4 解决的是“控制平面必须先统一”，那么 V11.0.1 要解决的就是：

> **如何让这套统一后的控制平面，成为一个成功率优先、资金轮转高效、能自我提升并持续进化的顶尖个人量化交易系统。**
