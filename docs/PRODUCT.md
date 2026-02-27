# 产品需求文档 (PRD)

> **AI量化交易闭环系统** - 个人美港股智能交易平台  
> 版本：V10.3 | 更新日期：2026-02-27  
> 变更摘要（V10.3）：**交易全链路可观测性（Full Trade Observability）**——Trade Lifecycle Center（交易生命周期中枢）双维度可视化（计划生命周期状态机 + 持仓生命周期状态机）+ 实时甘特泳道图；**智能订单簿（Intelligent Order Book）**——统一交易列表（标的/方向/价位/17阶段进度/AI简述/实时P&L/风险标记），替代分散的 AI Advisor + Journal 孤岛视图；**AI 决策溯源面板（Decision Provenance）**——从原始信号到最终执行的完整因果链可视化；**系统态势感知栏（System Situational Awareness Bar）**——全局粘性状态栏，实时聚合体制/VaR水位/事件围栏/活跃阶段/执行队列等关键状态  
> 变更摘要（V10.2-M2~M8）：**事件驱动风控**——EventCalendarService 盈利/FOMC/CPI/NFP 日历同步 + EarningsFenceService 盈利围栏（盈利前1天50%仓位上限）；**动态仓位生命周期**——PositionStateMachine 三引擎（ScaleIn/ScaleOut/TrailingStop）；**信号融合**——SignalFusionEngine 六维加权评分（tech 25%/fundamental 20%/macro 15%/vol 15%/opt 15%/sentiment 10%）+ 体制倍数；**交易归因**——TradeAttributionEngine 三层分析（Alpha源/执行质量/仓位管理）+ AttributionPage 可视化；**AI 进化**——InsightService 自动周报（deepseek-reasoner Sunday 22:00 ET）+ ABTestEngine（scipy t-test p<0.05）+ EvolutionPage；**Copilot Partner**——DeepResearchEngine 多步深度研究 + ProactiveIntelligenceService 主动推送  
> 变更摘要（V10.2-M1）：**市场体制感知引擎** ——RegimeClassifier 五维评分体系（趋势强度/波动率制度/量价关系/宏观环境/广度指标）、6类体制自动识别（BULL_TREND / BEAR_TREND / HIGH_VOL / MEAN_REVERT / RANGE_BOUND / CRISIS）、3日确认防噪机制、EventBus 异步事件总线（REGIME_CHANGED 事件驱动策略权重自适应切换、VaR 门限动态调整）、StrategyWeightAllocator 体制感知仓位分配、AI 自主交易闭环升级至 **17 阶段**  
> 变更摘要（V10.1）：**兑现承诺 + 打磨质量 + 扩展边界**——Tiger 真实下单接入（覆盖美股/港股/期权）、FULL 模式完整自主交易闭环、Copilot 操作指令执行落地、Dashboard 所有 TODO 指标真实化、AI 组合级决策升级（结构化 JSON 输出 + 批量组合决策）、ETF 标的池正式支持、港股支持（Tiger API 统一，无需 Futu）、Paper→Live 毕业自动化、Dashboard WebSocket 实时推送；**本版本明确不含 Telegram 通知，FULL 模式具备完全自主交易能力**

> 历史版本：V10.0（2026-02-24）变更摘要见下方历史记录节

---

## 1. 产品愿景

打造**全自主量化交易 AI**：系统 7×24 自主运行完整交易闭环，人工只需设定边界（风险预算、标的池、自主度等级），AI 处理其余一切——从市场研究到下单执行，从自我复盘到策略进化。

### 1.1 核心理念

**Autonomous Alpha Loop（自主阿尔法闭环）**：

```
┌─────────────────────────────────────────────────────┐
│              AI 自主决策引擎（全天候运行）              │
│                                                       │
│  市场扫描 → 信号生成 → 组合决策 → 风险审查 → 自动执行  │
│      ↑                                        ↓      │
│  策略进化 ← 参数优化 ← 绩效归因 ← 结果分析 ← 持仓监控  │
│                                                       │
│  [人工层] 设定边界 / 审计日志 / 随时干预 / Copilot 查询│
└─────────────────────────────────────────────────────┘
```

**三层自主度模式**（全局配置 `AI_AUTONOMY_LEVEL`）：

| 模式 | 值 | AI 行为 | 人工角色 |
|------|----|---------|---------|
| **全自主** | `FULL` | AI 自主完成完整闭环，无需任何人工确认 | 设定边界 + 审计 |
| **半自主** | `SEMI` | AI 生成决策并执行，重大操作（单笔 > N%）推送通知 | 重大操作可在30分钟内撤销 |
| **建议模式** | `ADVISORY` | AI 生成所有建议，所有执行需人工确认 | 审核并点击确认 |

> **默认模式**：`SEMI`（半自主）——兼顾效率与安全，推荐个人实盘使用。

### 1.2 标的类型限制

**默认仅支持股票（STOCK）**，通过配置 `ALLOWED_ASSET_TYPES` 扩展：

```
ALLOWED_ASSET_TYPES=STOCK              # 默认：仅股票
ALLOWED_ASSET_TYPES=STOCK,ETF          # 扩展：股票+ETF
ALLOWED_ASSET_TYPES=STOCK,ETF,OPTION   # 开启期权（需谨慎）
```

- 策略库中涉及期权的策略（尾部对冲、铁鹰、波动率套利）在 `STOCK` 模式下自动跳过
- 期权分析中心作为**只读信息工具**，不受此限制（仍可看 IV、P/C Ratio 等指标辅助判断）

### 1.3 北极星指标

| 指标 | V9 目标 | V10 目标 |
|------|---------|---------|
| 交易闭环覆盖 | 100% | 100%（全自主） |
| 人工日常操作步数 | ≤ 5 步 | **0 步**（FULL 模式）/ ≤ 3 步（SEMI） |
| 信号到执行延迟 | < 3s（通知） | **< 5s**（直接执行） |
| AI 自主决策收益率 | N/A | ≥ SPY 年化收益 |
| Paper→Live 策略升级率 | N/A | ≥ 70%（回测胜率 ≥ 55% 才升级） |
| 系统可用性 | ≥ 99.5% | ≥ 99.5% |

---

## 2. 用户画像

### 2.1 目标用户

- **被动量化投资者**：希望 AI 全权管理，自己只审计结果
- **主动量化研究者**：配置策略池和参数，观察 AI 自主运行效果
- **人机协作交易者**：保留 ADVISORY 模式，借助 AI 提升决策质量

### 2.2 核心痛点（V10 升级应对）

| 痛点 | V9 应对 | V10 应对 |
|------|---------|---------|
| 信息过载，难以决策 | AI 给建议 | **AI 直接决策+执行**，人只看结果 |
| 执行拖延 | 推送通知让用户确认 | **零人工摩擦**（FULL 模式自动执行） |
| 复盘困难 | 手动填写日志 | **AI 自动生成**完整交易复盘+周报 |
| 风险失控 | 风险评分提示 | **AI 主动管理风险**（止损/对冲/减仓）|
| 情绪交易 | 行为评分提醒 | **消除人类情绪**（AI 无情绪，严格守纪）|

---

## 3. 系统功能架构

### 3.1 AI 自主交易闭环（V10.2 升级：17 阶段）

```
0⃣ Regime Classification（体制分类）★ V10.2-M1 新增
    ↓ 五维评分 → 6类体制识别 → 3日确认 → EventBus 广播 REGIME_CHANGED
① Market Scan（市场扫描）
    ↓ DataHub 多源行情 + 宏观风险实时评估
② Research（研究分析）
    ↓ 12大类策略并行扫描 + AI 多维评分
③ Signal Generation（信号生成）
    ↓ 信号引擎聚合，AI 决定候选标的
③.₅ Signal Fusion（信号融合）★ V10.2-M4 新增
    ↓ 多源信号聚合 + 体制权重加成 + Shapley 归因
④ Portfolio Decision（组合决策）
    ↓ Markowitz/风险平价/Kelly 最优仓位计算
④.₅ Regime-Aware Position Sizing（体制感知仓位）★ V10.2-M2 新增
    ↓ 按当前体制动态调整策略权重与仓位上限
⑤ Risk Gate（风险门禁）
    ↓ 体制自适应 VaR 门限 + CVaR 检查 + 压力测试
⑥ Execution（智能执行）
    ↓ 小单直接下单 / 大单 TWAP/VWAP 拆分
⑦ Monitoring（持续监控）
    ↓ 实时跟踪 + 止损/止盈自动触发
⑦.₅ Event-Driven Override（事件驱动干预）★ V10.2-M3 新增
    ↓ 重大事件（FOMC/财报）自动触发仓位保护
⑧ Evaluation（绩效评估）
    ↓ 每日 PnL 归因 + Alpha/Beta + 体制归因分解
⑧.₅ TCA Analysis（交易成本分析）★ V10.2-M6 新增
    ↓ 滑点/冲击成本/执行质量量化
⑨ Backtest Validation（回测验证）
    ↓ 策略参数变更前先跑 Walk-Forward 回测
⑨.₅ AI Self-Evolution（AI 自我进化）★ V10.2-M5 新增
    ↓ 策略权重参数在线学习 + 因子效力衰减监测
⑩ Adaptive Optimization（自适应优化）
    ↓ AI 自动调整策略权重 + 参数
⑪ Loop（自主循环）
    → 回到 0⃣ 持续进化，无需人工介入
```

**人工在哪里？**
- 初始化：设定风险预算、标的池、自主度等级
- 运行中：通过 Copilot 随时查询，重大操作（SEMI 模式）收通知可撤销
- 复盘：查看 AI 自动生成的周报，调整边界配置

### 3.2 核心模块

#### A. 数据与研究层
- **DataHub 多数据源聚合**：Tiger（实时，覆盖美股/港股/期权）→ yfinance（美股降级）→ Redis 缓存，优先级路由；港股及期权行情与美股股票使用同一套 Tiger API 优先策略，无需独立数据源
- **市场热点分析**：识别热门赛道和个股
- **宏观风险评分**：地缘政治 + 经济指标综合判断
- **技术面分析**：多指标技术分析（AI 自主触发）
- **基本面分析**：估值 + 成长性评估
- **事件日历** ★ V10.2-M2：yfinance 盈利日历 + 硬编码 FOMC/CPI/NFP，每日 07:00 同步，风险分级（LOW/MEDIUM/HIGH/CRITICAL）

#### B. AI 决策层（V10 核心升级）
- **策略库**：12大类量化策略（股票模式下跳过期权策略）
- **组合智能**：Markowitz + 风险平价 + Kelly，从单标的决策升级为组合视角
- **AI 自主决策引擎**：deepseek-reasoner / gpt-5.2 驱动，自主完成建议→决策全流程
- **风险门禁**：VaR/CVaR + 压力测试，双重把关，AI 不绕过
- **信号融合引擎** ★ V10.2-M4：六维加权融合（tech 25% / fundamental 20% / macro 15% / vol 15% / options 15% / sentiment 10%）+ 体制倍数加权
- **盈利围栏** ★ V10.2-M2：盈利前 1 天自动激活 50% 仓位上限，防止盈利期决策扭曲

#### C. 执行层
- **智能执行路由**：小单市价 → 大单 TWAP/VWAP 自动选择
- **Paper/Live 双轨**：新策略先走 Paper，回测通过后升级 Live
- **止损/止盈引擎**：AI 动态更新止损位（追踪止损）
- **动态仓位生命周期** ★ V10.2-M3：PositionStateMachine 三引擎（ScaleInEngine：盈利回调触发加仓；ScaleOutEngine：超目标分批减仓；TrailingStopEngine：14日 ATR 移动止损）

#### D. 监控与复盘层
- **价格告警**：条件触发，AI 自动评估是否需要干预
- **AI 自动复盘**：交易日志自动填写，AI 生成质量评估
- **AI 周报**：每周日自动推送 Telegram，全面覆盖收益/策略/行为三个维度
- **行为评分**：对 AI 自身决策质量打分（替代人类行为评分）
- **交易归因引擎** ★ V10.2-M5：三层向下钻取——Alpha 源贡献（策略/信号）/ 执行质量（滑点/时机）/ 仓位管理（加减仓/止损效果）
- **AI 进化引擎** ★ V10.2-M6：InsightService 自动抽取洞察（每周日 deepseek-reasoner）、ABTestEngine 策略 A/B 实验（scipy t-test 显著性检验，p<0.05 自动结论）
- **Copilot Partner** ★ V10.2-M7：DeepResearchEngine 多步深度研究报告（市场情绪→基本面→风险因素→综合评级）、ProactiveIntelligenceService 主动推送重大事件摘要

---

## 4. 核心功能详述

### 4.1 AI 自主决策引擎（Autonomous Decision Engine）

**V10 核心升级**：不再是"AI 给建议 → 人决策"，而是"AI 直接决策并执行，人设定边界"。

**决策流程**：
```
1. 触发条件满足（定时 or 事件驱动，如价格突破/宏观事件）
2. AI 并行运行：技术面 + 基本面 + 宏观 + 策略信号 四维评分
3. 组合优化：计算最优仓位分配（Kelly/Markowitz）
4. 风险门禁：VaR 检查 + 压力测试（不通过则拒绝执行）
5. 决策记录：写入审计日志，推送 Telegram 通知（SEMI 模式）
6. 执行：小单市价 / 大单 TWAP/VWAP，独立的 Paper 或 Live 账户
```

**AI 决策输出**（完整 JSON）：
```json
{
  "decision_id": "uuid",
  "symbol": "AAPL",
  "asset_type": "STOCK",
  "direction": "LONG",
  "confidence": 78,
  "action": "BUY",
  "entry_price": 178.50,
  "stop_loss": 175.00,
  "take_profit": 186.00,
  "position_pct": 0.12,
  "kelly_fraction": 0.18,
  "portfolio_adjusted_pct": 0.12,
  "risk_level": "MEDIUM",
  "var_impact": -0.008,
  "execution_algo": "TWAP",
  "account_type": "PAPER",
  "autonomy_action": "AUTO_EXECUTE",
  "reasoning": "技术面强势(82分)，基本面健康(75分)，宏观低风险(68分)，Kelly建议18%但组合优化后压缩至12%",
  "scenarios": { "bull": { "prob": 0.45, "target": 186 }, "bear": { "prob": 0.25, "target": 172 } },
  "model_used": "deepseek-reasoner",
  "created_at": "2026-02-24T09:30:00Z"
}
```

**自主度控制**：
```
FULL  → autonomy_action = AUTO_EXECUTE（直接执行）
SEMI  → autonomy_action = AUTO_EXECUTE（执行后推送可撤销通知，30分钟内可撤）
ADVISORY → autonomy_action = PENDING_CONFIRM（等待人工确认）
```

**AI 模型路由**：
```
轻量决策辅助（技术指标计算、信号评分）→ deepseek-chat / gpt-4o-mini
核心交易决策（多维综合分析、组合优化）→ deepseek-reasoner / gpt-5.2
```

**决策安全边界**（AI 不可突破）：
- 单标的仓位 ≤ `MAX_SINGLE_POSITION_PCT`（默认 25%）
- 总风险敞口（VaR@95%）≤ `MAX_VAR_PCT`（默认 3%）
- 单日最大交易笔数 ≤ `MAX_DAILY_TRADES`（默认 10）
- 压力测试最大损失 ≤ `MAX_STRESS_LOSS_PCT`（默认 15%）
- 标的类型 ∈ `ALLOWED_ASSET_TYPES`（默认 STOCK）

### 4.2 交易计划（AI 自动生成 + 可选人工审核）

**V10 变化**：计划不再需要人工创建，AI 自主生成并根据自主度等级决定是否自动执行。

**生命周期**：
```
AI_GENERATED → [SEMI/FULL: AUTO_EXECUTING] / [ADVISORY: PENDING_CONFIRM]
                         ↓
              EXECUTED / CANCELLED / EXPIRED / FAILED
```

**来源字段** `source`：
- `AI_AUTONOMOUS`：AI 自主决策生成（V10 主流）
- `AI_ADVISORY`：AI 建议，人工确认（ADVISORY 模式）
- `MANUAL`：用户手动创建

**撤销机制**（SEMI 模式专用）：
- AI 执行后推送 Telegram："已执行 AAPL 买入 $178.50 × 100股 [撤销链接]"
- 30分钟内点击撤销链接，系统自动平仓（同价区间内市价反向）
- 超时则确认，写入日志

### 4.3 策略库（股票模式 = 10 类策略，期权模式 = 12 类）

**股票模式下启用（`ALLOWED_ASSET_TYPES=STOCK`）**：

#### A. 均值回归策略
1. **布林带均值回归** - 价格偏离均线 > 2σ
2. **配对交易** - 协整股票对价差（纯股票对）

#### B. 趋势跟踪策略
3. **突破动量** - 突破关键阻力/支撑位
4. **黄金交叉** - 短期均线上穿长期均线

#### C. 多因子策略
5. **Fama-French 三因子** - 市场/规模/价值因子
6. **动量+质量** - ROE + 价格动量综合

#### D. 防御策略
7. **低波动率** - 选择历史波动率最低的股票标的
8. **~~尾部对冲~~** ⛔ _仅 OPTION 模式可用_

#### E. 波动率策略（**仅参考，不执行**）
9. **~~铁鹰期权~~** ⛔ _仅 OPTION 模式可用_
10. **~~波动率套利~~** ⛔ _仅 OPTION 模式可用_

#### F. 宏观对冲策略
11. **行业轮动** - 经济周期驱动的板块切换（用股票 ETF 实现）
12. **CTA 商品** - 商品 ETF 趋势跟踪

**AI 自主策略调度**：
- 每日盘前 08:30 自动运行全部启用策略
- 宏观风险高（≥ 70分）时，自动提升防御策略权重
- 策略参数由 AdaptiveOptimizer 每日回测验证后自动更新

### 4.4 组合决策（Portfolio-Level AI Decision）

**V10 新增核心功能**：AI 不再逐个信号独立决策，而是**在组合层面统一决策**。

**流程**：
```
当日信号池（N个候选标的）
    ↓
AI 评分矩阵（技术 × 基本面 × 宏观 × 策略权重）
    ↓
协方差矩阵计算（过去252日日线收益率）
    ↓
Markowitz 最优化（最大化夏普，约束条件：VaR、仓位上限）
    ↓
Kelly 仓位修正（以 Half-Kelly 保守压缩）
    ↓
输出：最终执行标的列表 + 各标的仓位比例
```

**约束条件**（AI 强制遵守）：
- 总仓位 ≤ 95%（保留5%现金缓冲）
- 单行业集中度 ≤ 40%
- 与基准（SPY）相关性 ≤ 0.9（防止纯 Beta 持仓）

### 4.5 风险门禁（Risk Gate—AI 自我约束）

**定位**：AI 决策完成后、执行前的最后一道程序化护栏，不可配置关闭。

**检查链（串行，任一失败则拒绝）**：
```
① VaR@95% 检查：执行后组合 VaR ≤ MAX_VAR_PCT
② 压力测试快速版：COVID_2020 情景下损失 ≤ MAX_STRESS_LOSS_PCT
③ 仓位合规检查：单标的、行业集中度不超限
④ 标的类型检查：符合 ALLOWED_ASSET_TYPES
⑤ 频率检查：今日交易笔数未超 MAX_DAILY_TRADES
```

**拒绝后 AI 处理**：降低仓位比例后重新检查，若仍不过则放弃本次信号并记录原因。

### 4.6 回测验证（Backtest Validation—策略升级前置条件）

**Paper→Live 升级流程**：
```
新策略/参数变更
    ↓
自动触发 Walk-Forward 回测（最近2年日线，70/30 训练/测试集）
    ↓
评估：Sharpe ≥ 1.0 AND 最大回撤 ≤ 20% AND 胜率 ≥ 50%？
    ↓ 通过            ↓ 失败
Paper 账户运行30天  → 保留旧参数，记录失败原因
    ↓ Paper 胜率 ≥ 55%
升级 Live 账户（逐步放量：首月25% → 次月50% → 第三月100%）
```

**回测指标**：年化收益、最大回撤、Sharpe、Sortino、Calmar、胜率、盈亏比、Alpha vs SPY

### 4.7 Trading Copilot（人机协同接口）

**定位**：人工唯一主动交互入口，替代散落的按钮操作。用自然语言查询、下指令、或紧急干预。

**能力**：
- **查询**："今天 AI 做了哪些交易？""NVDA 当前持仓的盈亏是多少？"
- **分析**："当前组合的最大风险来自哪里？"（触发 deepseek-reasoner 深度分析）
- **指令**（需二次确认）："暂停所有自动交易""把 AAPL 止损改到175""清仓 TSLA"
- **配置**："把自主度切换到 ADVISORY 模式""把 NVDA 加入禁止交易名单"
- **主动推送**：盘前摘要（AI 今日计划）、异常事件提醒、盘后日报、周报

**AI 分层**：
```
查询类（单轮，上下文少）  → deepseek-chat / gpt-4o-mini（速度优先）
分析类（多轮，需推理）    → deepseek-reasoner / gpt-5.2（质量优先）
指令类                    → 固定逻辑处理，不走 LLM（安全优先）
```

### 4.8 TWAP/VWAP 执行算法

**AI 自动选择**（无需人工干预）：

| 条件 | 选择算法 |
|------|---------|
| 订单金额 < 账户净值 1% | 市价单（立即执行） |
| 订单金额 1%~5% | VWAP（30分钟） |
| 订单金额 > 5% | TWAP（60分钟，6份拆分） |
| 宏观风险 ≥ HIGH | 紧急模式：忽略大小，强制市价 |

### 4.9 AI 自动复盘与周报

**日报**（每日收盘后自动生成）：
- 今日 AI 决策汇总（执行了什么 / 为什么 / 结果如何）
- 策略贡献热力图
- 风险指标变化

**周报**（每周日 21:00 自动生成 + 推送 Telegram）：
```
📊 AI Alpha 周报 (2026-WXX)

📈 收益概览：本周 +2.3% vs SPY -0.5%（Alpha +2.8%）
🤖 AI 决策质量：置信度均值 73 / 胜率 62% / 平均 R:R 1:2.4
🎯 策略贡献：布林带 +1.1% / 低波动率 +0.8% / 突破动量 -0.3%
⚡ 执行质量：TWAP 滑点 0.06%（目标 < 0.1%）
🛡 风险回顾：最大日内 VaR 2.1%（上限 3%），安全
🔄 自适应更新：突破动量止损参数从 2.0% → 2.5%（回测改善 Sharpe +0.2）
💡 下周展望：宏观风险偏高，防御权重 +10%
```

---

## 4.X V10.2-M2~M7 新增功能详述

### 4.X.1 事件日历 & 盈利围栏（M2）

**目标**：在盈利/FOMC/CPI 等高影响力事件前，AI 自动收紧仓位管理，防止意外冲击。

**盈利围栏机制**：
- 盈利公布前 `PREEARNING_DAYS`（默认 1）天激活围栏
- 围栏激活 → 新建仓位和加仓操作自动上限 50%（`EARNINGS_FENCE_CAP=0.5`）
- 围栏可人工覆盖（需填写理由）
- 盈利结果录入后：自动解除围栏 + 记录 EPS 实际值与价格反应

**事件类型**：
| 事件类型 | 数据来源 | 风险等级 |
|---------|---------|---------|
| 单股盈利（EARNINGS）| yfinance.Ticker.calendar | HIGH/CRITICAL |
| FOMC 会议 | 硬编码 2025 年全年 | CRITICAL |
| CPI 数据 | 硬编码 2025 年全年 | HIGH |
| NFP 就业报告 | 硬编码 2025 年全年 | HIGH |

---

### 4.X.2 动态仓位生命周期（M3）

**目标**：用规则驱动的状态机取代静态止盈止损，实现持仓全生命周期精细化管理。

**PositionStateMachine 状态**：`INITIAL → PARTIAL → FULL → REDUCING → CLOSED`

**三类引擎触发条件**：

| 引擎 | 触发条件 | 操作 |
|------|---------|------|
| ScaleInEngine（加仓）| 价格从高点回调 > 30% × ATR，且原方向信号仍有效 | 加仓 25-50% |
| ScaleOutEngine（减仓）| 价格超过止盈目标 1.5× | 减仓 30-50% |
| TrailingStopEngine（移动止损）| 盈利超 1×ATR 后启用移动止损（Price - N×ATR，N=14日）| 动态更新止损位 |

---

### 4.X.3 六维信号融合（M4）

**目标**：取代单一技术信号，聚合六大数据维度形成高置信度融合信号，直接驱动 AI 决策。

**六维权重体系**（基础权重，体制可调整）：

| 维度 | 基础权重 | BULL_TREND 倍数 | CRISIS 倍数 |
|------|---------|---------------|------------|
| 技术面（Tech）| 25% | ×1.3 | ×0.8 |
| 基本面（Fundamental）| 20% | ×1.0 | ×0.9 |
| 宏观（Macro）| 15% | ×0.9 | ×1.5 |
| 波动率（Volatility）| 15% | ×0.9 | ×1.3 |
| 期权（Options）| 15% | ×1.1 | ×1.2 |
| 情绪（Sentiment）| 10% | ×1.0 | ×0.7 |

`composite_score = Σ(dim_score × effective_weight)`，归一化到 0-100。

---

### 4.X.4 三层交易归因（M5）

**目标**：让每笔已平仓交易的盈亏来源清晰可追溯，驱动 AI 策略自我进化。

**三层模型**：

```
总 PnL
├── Layer 1 — Alpha 源归因
│   识别哪个信号维度/策略带来超额收益
│   alpha_pnl = total_pnl × alpha_contribution_ratio
│
├── Layer 2 — 执行质量归因
│   量化滑点/时机差异对结果的影响
│   exec_pnl = (actual_fill - theoretical_price) × qty
│   exec_quality_score = 100 × (1 - |slippage_bps| / 50)
│
└── Layer 3 — 仓位管理归因
    量化加减仓决策和移动止损的贡献
    pos_mgmt_pnl = scale_in_gain + trailing_stop_savings
```

---

### 4.X.5 AI 自我进化引擎（M6）

**目标**：AI 像有记忆的专业交易员一样，从历史交易中提炼规律并持续改进。

**两大组件**：

1. **InsightService（周报洞察）**
   - 每周日 22:00 ET 由 `deepseek-reasoner` 自动运行
   - 分析过去 7 天 trade_attribution_entries
   - 生成 4 类洞察：WEEKLY_SUMMARY / PATTERN / LESSON / RULE_CANDIDATE
   - 洞察写入 `ai_insight_repository`，可人工激活/停用

2. **ABTestEngine（A/B 实验）**
   - 支持创建任意参数维度的对照实验（止损倍率/信号阈值等）
   - 每日 08:30 运行 `scipy.stats.ttest_ind` 双样本 t-test
   - p < 0.05 → 自动标记显著 + 生成结论
   - EvolutionPage 可视化所有实验状态与结果

---

### 4.X.6 Copilot Partner（M7）

**目标**：将 Copilot 从"被动 QA 助手"升级为"主动研究合伙人"。

**两大升级**：

1. **DeepResearchEngine（深度研究）**
   - `POST /api/v1/copilot/deep-research` 触发
   - 对任意标的执行 4步多轮推理：
     1. 市场情绪与近期走势分析
     2. 基本面价值评估（PE/增长/护城河）
     3. 风险因素清单（监管/竞争/宏观）
     4. 综合评级 + 价格目标区间
   - 返回结构化报告：`{rating, price_target, body, sources[]}`

2. **ProactiveIntelligenceService（主动推送）**
   - 订阅 EventBus 所有 Topic
   - 当 REGIME_CHANGED / EVENT_CALENDAR_UPDATED / CIRCUIT_BREAKER_TRIGGERED 等重大事件发生时
   - 自动通过 Copilot 推送摘要，无需用户主动询问

---

## 4.Y V10.3 新增功能详述——交易全链路可观测性（Full Trade Observability）

> **设计哲学（华尔街顶级量化标准）**  
> Citadel / Two Sigma 等机构核心教训：**AI 自主交易系统最大的风险不是决策错误，而是决策不透明**。当系统处于 FULL 自主模式时，人工唯一能做的是"观察并在边界处干预"——这要求系统以接近彭博终端级别的信息密度与实时性，将交易全链路的每一个状态节点暴露给审计者。V10.3 核心命题：**让 AI 的每一个动作都在玻璃墙后面运行**。

---

### 4.Y.1 核心设计原则

| 原则 | 具体体现 | 量化目标 |
|------|---------|---------|
| **全链路状态透明** | 每笔交易从信号诞生到平仓的每一步均有时间戳与状态标记 | 信息缺口率 = 0（无黑洞阶段）|
| **双维度生命周期** | 计划生命周期（Plan FSM）+ 持仓状态机（Position FSM）正交展示 | 任何交易可在 2 秒内定位当前所处阶段 |
| **17 阶段流水线可视化** | 实时 Kanban 泳道，每笔任务在流水线上的位置实时更新 | 流水线延迟异常检测 P95 < 10s |
| **AI 决策因果链溯源** | 从原始多维信号 → 融合评分 → 风险门禁 → 执行算法，每步决策依据可查 | 任意交易 → 完整 provenance 链路 < 3 次点击 |
| **异常驱动告警** | 状态机异常转换（如 FULL→CLOSED 跳跃 ScaleOut）自动标红 | 异常捕获率 100%，误报率 < 5% |
| **横向比较视图** | 多标的并排在同一时间轴上展示生命周期进展 | 同屏展示 ≤ 20 笔活跃交易 |

---

### 4.Y.2 Trade Lifecycle Center（交易生命周期中枢）

**定位**：系统新增一级核心页面（`/trade-lifecycle`），专门承载双维度生命周期可视化，是 V10.3 的旗舰功能。不替代现有 Journal/Positions 页，而是提供**动态过程视角**（Journal 记录结果，Lifecycle Center 展示过程）。

#### A. 顶部 — 17 阶段流水线泳道（Pipeline Kanban）

将 AI 自主闭环的 17 个阶段映射为横向泳道，每笔活跃交易任务（Task）在泳道中流动：

```
Stage 0   Stage 1    Stage 2    Stage③     Stage③.₅   Stage④      Stage④.₅   Stage⑤
体制分类  市场扫描   研究分析   信号生成   信号融合   组合决策   体制仓位    风险门禁
────────   ────────   ────────   ────────   ────────   ────────   ────────   ────────
           [NVDA]                [AAPL]                            [TSLA]
           [META]                                                  
                                 [MSFT]

Stage⑥    Stage⑦    Stage⑦.₅    Stage⑧    Stage⑧.₅   Stage⑨     Stage⑨.₅   Stage⑩    Stage⑪
智能执行  持续监控  事件干预    绩效评估   TCA分析   回测验证   AI进化    自适应优化  自主循环
────────   ────────  ────────   ────────   ────────   ────────   ────────   ────────   ────────
[AAPL]     [00700]              [NVDA]
           [AMZN]
```

**视觉规范**：
- 每个 Stage 列宽相等，任务卡片水平滚动
- 任务卡片颜色：
  - 🟢 正常流转（当前阶段时长在 P50 以内）
  - 🟡 轻度延迟（P50～P90）
  - 🔴 严重延迟（超 P90，触发告警）
  - ⚫ 已停滞（> 2× P95，需人工介入）
- 卡片悬停展示：当前阶段耗时、预计下阶段时间、置信度分数
- 点击任务卡片 → 跳转至底部 Decision Provenance 面板

**阶段聚合指标**（每列底部）：
- 当前滞留任务数
- 平均阶段耗时（与历史 P50 对比）
- 今日通过率（进入 → 通过 / 进入 → 总量）

---

#### B. 中部 — 双维度生命周期状态图（Dual FSM Panel）

左右分屏，同时展示两个维度的状态机：

**左侧 — 计划生命周期（Plan FSM）**：

```
                ┌──────────────────────────────────────────┐
                │ 计划生命周期（Plan Lifecycle）              │
                ├──────────────────────────────────────────┤
                │                                           │
  [AI_GENERATED] ──▶ [AUTO_EXECUTING] ──▶ [EXECUTED] ──▶ (归因) 
        │                  │                   │
        │ (ADVISORY)       │ 30min内            │
        ▼                  ▼                   │
  [PENDING_CONFIRM] ──▶ [REVOKED]            [FAILED]
        │
        ▼                              [CANCELLED]  [EXPIRED]
  [AUTO_EXECUTING]
                │
                ├──────────────────────────────────────────┤
                │ 活跃计划数: 3  今日已完成: 12  撤销: 1   │
                │ FULL:2  SEMI:1  ADVISORY:0               │
                └──────────────────────────────────────────┘
```

- 状态节点圆圈：包含当前处于该状态的计划数量（实时）
- 状态转换箭头：鼠标悬停显示触发条件
- 点击任意状态节点 → 底部列表过滤至该状态的计划

**右侧 — 持仓状态机（Position FSM）**：

```
                ┌──────────────────────────────────────────┐
                │ 持仓状态机（Position State Machine）       │
                ├──────────────────────────────────────────┤
                │                                           │
  [INITIAL] ──▶ [PARTIAL] ──▶ [FULL] ──▶ [REDUCING] ──▶ [CLOSED]
      │               ▲          │              │               
      │    ScaleIn     │  ScaleIn │  ScaleOut    │  TrailingStop
      │               │          ▼              ▼
      │               └──── [持仓加仓中]    [持仓减仓中]
      │                    (+25~50%)        (-30~50%)
      │
      │ (直接止损/风险门禁触发强制平仓)
      └────────────────────────────────▶ [CLOSED]
                │
                ├──────────────────────────────────────────┤
                │ INITIAL:1  PARTIAL:3  FULL:5             │
                │ REDUCING:2  CLOSED (今日):8               │
                │ 引擎触发次数: ScaleIn×3 ScaleOut×2 TS×1  │
                └──────────────────────────────────────────┘
```

**状态转换事件日志**（FSM 面板底部，滚动）：
```
10:32:15  AAPL   PARTIAL → FULL      ScaleInEngine 触发，入场价 $183.2，加仓 40%
10:18:04  NVDA   FULL    → REDUCING  ScaleOutEngine 触发，超止盈1.5×目标
09:45:22  META   INITIAL → PARTIAL   首次建仓，Plan #2840 执行完成
09:31:00  TSLA   REDUCING→ CLOSED   TrailingStop 触发，ATR×14=5.3%，锁利 +8.2%
```

---

#### C. 底部 — AI 决策溯源面板（Decision Provenance Drawer）

点击任意交易任务卡片展开，展示一笔交易的**完整因果链**：

```
┌─ AAPL BUY $183.20 × 120股 ─────────────────────────────────────────┐
│ 决策 #2847 | 置信度 78 | 状态: EXECUTING | 创建 10:14:32             │
├───────────────────────────────────────────────────────────────────┤
│ 📡 原始信号来源（SignalFusionEngine 输入）                           │
│ ┌────────────┬────────┬──────────┬────────────────────────────┐  │
│ │ 维度        │ 原始分  │ 体制权重  │ 最终贡献                    │  │
│ ├────────────┼────────┼──────────┼────────────────────────────┤  │
│ │ 技术面      │ 82     │ ×1.3     │ 26.7 / 32.5               │  │
│ │ 基本面      │ 75     │ ×1.0     │ 15.0 / 20.0               │  │
│ │ 宏观        │ 68     │ ×0.9     │ 9.2  / 13.5               │  │
│ │ 波动率      │ 71     │ ×0.9     │ 9.6  / 13.5               │  │
│ │ 期权        │ 65     │ ×1.1     │ 10.7 / 16.5               │  │
│ │ 情绪        │ 70     │ ×1.0     │ 7.0  / 10.0               │  │
│ ├────────────┴────────┴──────────┴────────────────────────────┤  │
│ │ 综合评分: 78.2  当前体制: BULL_TREND（置信度 85%）              │  │
│ └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│ ⚖️ 风险门禁检查链（全部通过 ✅）                                    │
│  ✅ VaR@95%: 执行后 2.4%  ≤ 3.0% 上限                            │
│  ✅ 压力测试: COVID_2020 场景损失 8.3%  ≤ 15% 上限               │
│  ✅ 仓位合规: 单标的 12%  ≤ 25% 上限                              │
│  ✅ 标的类型: STOCK ∈ ALLOWED_ASSET_TYPES                        │
│  ✅ 频率: 今日 3 笔  ≤ 10 笔上限                                  │
│                                                                    │
│ 🤖 AI 决策摘要（from reasoning 字段）                              │
│  "技术面强势(82分)，BULL_TREND 体制下技术权重上调至1.3×；基本面     │
│   健康(75分)，Q4 EPS 超预期12%；组合优化后从 Kelly 建议18%压缩至    │
│   12%，TWAP 30分钟执行（订单约占净值 2.1%）"                       │
│                                                                    │
│ ⚡ 执行详情（ExecutionAlgo）                                       │
│  算法: TWAP  时长: 30min  拆单: 6份 × 20股                        │
│  已成交: 4/6份  均价: $183.18  目标均价: $183.20  滑点: -0.01%   │
│                                                                    │
│ [查看完整 JSON] [跳转归因分析] [跳转持仓] [撤销交易]               │
└───────────────────────────────────────────────────────────────────┘
```

---

### 4.Y.3 智能订单簿（Intelligent Order Book）

**定位**：新增页面 `/order-book`，统一替代分散在 AI Advisor + Journal + Positions 中的交易列表视图。提供**实时更新的全量交易视图**，包含今日活跃 + 近 7 天历史。

#### 主列表设计（每行信息密度对标 Bloomberg Terminal Order Sheet）：

| 字段 | 内容 | 样式 |
|------|------|------|
| **标的** | 代码 + 中英文名 + 市场标签（US/HK）+ 资产类型图标 | 主字段，可点击跳转 |
| **方向** | LONG ↑ / SHORT ↓ | 绿/红色方向箭头 |
| **触发阶段** | 信号诞生于哪个模块（策略名称缩写） | 策略徽章（色码） |
| **当前阶段** | 17 阶段中的具体阶段编号 + 名称 | 进度徽章 |
| **入场目标价** | AI 建议入场区间（low ～ high） | 价格组 |
| **实际成交均价** | 已成交时显示，偏差用颜色标记 | 实际 vs 目标对比 |
| **止损价** | 当前动态止损位（TrailingStop 实时更新）| 红色价位 |
| **止盈目标** | 原始 + 动态止盈位（ScaleOut 调整后）| 绿色价位 |
| **仓位 %** | 当前占净值比例（含 ScaleIn 后变动）| mini 进度条 |
| **浮盈 / PnL** | 实时浮盈金额 + 百分比 | 正绿负红 |
| **置信度** | 原始 AI 评分（0-100）+ 六维雷达迷你图 | 评分徽章 |
| **风险标记** | 盈利围栏 🔒 / 体制预警 ⚡ / 流动性警告 💧 | 图标徽章 |
| **AI 摘要** | reasoning 字段前 80 字，悬停展开全文 | Truncated text |
| **操作** | [详情] [撤销] [修改止损] | 操作按钮组 |

#### 列表视图布局：

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 📋 智能订单簿                    [活跃: 7] [今日已完成: 12] [待确认: 2]   [筛选▼] [导出] │
├────────────────────────────────────────────────────────────────────────────────────┤
│ 分组：▸ 活跃执行中 (3)            ▸ 持仓监控中 (4)            ▸ 今日已完成 (12)      │
│──────────────────────────────────────────────────────────────────────────────────── │
│ 🟢 活跃执行中                                                                        │
│ 标的        方向  策略源       当前阶段          入场目标     成交均价  止损    PnL    │
│ 🇺🇸AAPL    ↑BUY  [布林带]  ⑥执行·TWAP 4/6  $183.0~183.5  $183.18  $178.0  执行中  │
│ 概述: "技术强势(82)，BULL_TREND加权，Q4 EPS超预期，Kelly 18%→组合压至 12%"           │
│ ─────────────────────────────────────────────────────────────────────────────────  │
│ 🇺🇸NVDA    ↑BUY  [突破动量] ⑥执行·VWAP 1/3  $890.0~895.0  $891.30  $870.0  执行中  │
│ 概述: "突破关键阻力 $888，成交量放大 2.3×，情绪面超预期，配对 ETF 流入强劲"           │
│──────────────────────────────────────────────────────────────────────────────────── │
│ 🔵 持仓监控中                                                                        │
│ 标的        方向  策略源       当前阶段          成本价      现价      止损    浮盈    │
│ 🇺🇸MSFT    ↑LONG [Fama-FF]  ⑦监控·PARTIAL    $415.20   $428.50  $405.0  +$1,330  │
│ 🔒盈利围栏  [ScaleIn 可用]  "多因子强信号，ROE 40%+，PEG 1.8 合理估值区间"           │
│ ─────────────────────────────────────────────────────────────────────────────────  │
│ 🇭🇰00700   ↑LONG [行业轮动] ⑦监控·FULL       HK$356.0   HK$371.0  HK$348  +HK$3,000│
│ ⚡BEAR_TREND预警  "腾讯，港股互联网轮动信号，政策环境改善，体制权重已下调至0.8×"     │
└──────────────────────────────────────────────────────────────────────────────────── ┘
```

#### 辅助功能：

- **高级筛选**：按方向 / 资产类型 / 市场 / 阶段范围 / 策略来源 / 风险标记 / 账户类型（Paper/Live）
- **置信度六维迷你雷达图**：悬停在置信度数字上，展示六维蛛网图
- **价格偏差列**：成交均价与 AI 入场目标价对比（超差 > 0.3% 自动标黄）
- **批量操作**：全选活跃订单，批量 [修改止损] / [标记观察]

---

### 4.Y.4 系统态势感知栏（System Situational Awareness Bar）

**定位**：全局顶部粘性状态栏（高度 36px），在所有页面持续展示系统关键状态，取代需要点击进入专页才能看到的碎片化状态信息。灵感来源：Bloomberg Terminal 状态栏 + Citadel 内部 Risk Dashboard 常驻水位条。

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 🌊体制: BULL_TREND⬆85%  │ ⚠️VaR: 2.4%/3.0%[████████░░]  │ 📅围栏: MSFT🔒(明日财报)  │
│ ⑥执行中: AAPL·NVDA     │ 🕐等待确认: 2笔(ADVISORY)      │ 🤖FULL自主 ● 运行中      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**信息分区（从左到右优先级递减）**：

| 区块 | 内容 | 更新频率 | 颜色逻辑 |
|------|------|---------|---------|
| **体制状态** | 当前体制名称 + 置信度 + 趋势箭头 | 每日（体制确认后）| 体制类型色码 |
| **VaR 水位** | 当前 VaR% / 上限% + mini 进度条 | 每 5 分钟 | 绿/黄/红 |
| **事件围栏** | 今日/明日激活的盈利围栏标的 | 实时 | 橙色警告 |
| **活跃执行** | 正在执行的交易标的（TWAP/VWAP 进行中）| 实时 | 蓝色动画点 |
| **待确认** | ADVISORY 模式下等待人工确认的计划数 | 实时 | 若>0 则黄色闪烁 |
| **自主模式** | FULL/SEMI/ADVISORY + 运行/暂停状态 | 实时 | 绿色(运行)/红色(暂停) |

**点击任意区块** → 导航至对应详情页。
**ADVISORY 待确认 > 0** → 区块红色闪烁 + 点击直接展示确认面板。

---

### 4.Y.5 后端 API 新增需求

#### 交易生命周期查询接口

```
GET  /api/v1/lifecycle/pipeline              — 17 阶段流水线当前状态（所有活跃任务分布）
GET  /api/v1/lifecycle/plan-fsm              — 计划生命周期 FSM 状态统计（各状态计划数）
GET  /api/v1/lifecycle/position-fsm          — 持仓 FSM 状态统计（各状态持仓数 + 当日引擎触发次数）
GET  /api/v1/lifecycle/fsm-events            — FSM 状态转换事件流（最近 N 条，支持 offset）
GET  /api/v1/lifecycle/provenance/{plan_id}  — 单笔交易决策溯源完整链路
```

#### 订单簿接口

```
GET  /api/v1/order-book                      — 全量订单视图（活跃+今日历史，支持分页+筛选）
GET  /api/v1/order-book/summary              — 聚合摘要（活跃数/已完成/待确认/今日 PnL）
GET  /api/v1/order-book/{plan_id}/detail     — 单笔订单完整详情（含执行进度+仓位状态）
PATCH /api/v1/order-book/{plan_id}/stop-loss — 修改活跃持仓止损位（Copilot 指令下发）
```

#### 态势感知接口

```
GET  /api/v1/situational-awareness           — 全局状态聚合（体制/VaR/围栏/执行队列/自主模式）
WS   /ws/v1/situational-awareness            — WebSocket 推送（任意状态变更时实时推送）
```

---

### 4.Y.6 数据模型扩展

在现有 `trade_plan` 表新增字段：

```sql
-- 生命周期溯源字段
pipeline_stage      SMALLINT        -- 当前所处 17 阶段编号（0-17）
stage_entered_at    TIMESTAMPTZ     -- 进入当前阶段的时间戳
stage_history       JSONB           -- 各阶段进入/退出时间戳数组
provenance_snapshot JSONB           -- 决策溯源快照（六维分数 + 风险门禁结果）
position_fsm_state  VARCHAR(20)     -- 关联的 Position FSM 当前状态
```

在现有 `positions` / `position_states` 表新增：

```sql
fsm_transition_log  JSONB           -- 状态机转换事件日志（时间戳 + 触发引擎 + 操作详情）
engine_trigger_count JSONB          -- 各引擎触发计数 {scale_in: N, scale_out: N, trailing: N}
```

---

### 4.Y.7 北极星指标（V10.3）

| 指标 | 定义 | V10.3 目标 |
|------|------|-----------|
| 生命周期透明度 | 活跃交易中可完整追溯 provenance 链路的比例 | 100% |
| 状态延迟可见性 | 流水线异常（超 P90 阶段耗时）到告警展示的延迟 | < 10s |
| 决策可解释性 | 每笔执行交易可在 3 次点击内查到完整六维信号来源 | 100% |
| 订单簿实时性 | 执行状态更新到界面反映的延迟 | < 3s（WebSocket）|
| 态势感知准确性 | 系统实际状态与 Awareness Bar 展示一致率 | ≥ 99.9% |

---

## 5. 技术要求

### 5.1 性能指标

| 指标 | 要求 |
|------|------|
| AI 决策完成（含组合优化）| P95 < 8s |
| 信号到执行延迟 | < 5s（FULL 模式） |
| API 响应时间（非 AI） | P95 < 500ms |
| 回测任务（1年日线，1策略）| < 30s |
| Dashboard 刷新 | ≤ 30s |
| 系统可用性 | ≥ 99.5% |

### 5.2 AI 安全要求

- **决策可解释性**：每笔 AI 交易必须写入 `reasoning` 字段，可追溯
- **强制审计日志**：所有 AI 执行操作写入不可删除的 `audit_log` 表
- **熔断机制**：单日亏损 ≥ `MAX_DAILY_LOSS_PCT`（默认 3%）时自动暂停 AI 自动交易
- **人工覆盖权**：任何时刻调用 `/api/v1/autonomy/pause` 可立即暂停所有自动执行
- **标的白名单**：`ALLOWED_SYMBOLS` 配置项（空=全部允许）

### 5.3 配置边界（全局安全参数）

```bash
# AI 自主度
AI_AUTONOMY_LEVEL=SEMI           # FULL / SEMI / ADVISORY

# 标的类型限制
ALLOWED_ASSET_TYPES=STOCK        # STOCK / STOCK,ETF / STOCK,ETF,OPTION

# 风险边界（AI 不可突破）
MAX_SINGLE_POSITION_PCT=0.25     # 单标的最大仓位
MAX_VAR_PCT=0.03                 # 组合最大 VaR@95%
MAX_STRESS_LOSS_PCT=0.15         # 压力测试最大容忍损失
MAX_DAILY_TRADES=10              # 单日最大交易笔数
MAX_DAILY_LOSS_PCT=0.03          # 单日亏损熔断线

# Paper Trading
PAPER_INITIAL_CAPITAL=100000     # Paper 账户初始资金
PAPER_AUTO_GRADUATE=true         # 是否自动升级符合条件的策略到 Live

# 数据源（美股/港股/期权统一使用 Tiger API 优先）
DATA_HUB_PRIMARY=tiger           # tiger / yfinance
DATA_HUB_FALLBACK=yfinance        # Tiger 不可用时降级 yfinance（主要覆盖美股）
# 港股/期权行情：Tiger API 为唯一正式来源，不引入 Futu API

# AI 模型
AI_LIGHTWEIGHT_MODEL=deepseek-chat    # 轻量决策
AI_COMPLEX_MODEL=deepseek-reasoner    # 复杂分析
```

### 5.4 安全与合规

- JWT 认证 + bcrypt 密码加密
- API Rate Limit（100 req/min）
- 敏感操作 + AI 决策 双重审计日志
- 熔断记录、撤销记录完整保存 ≥ 180 天

---

## 6. 成功标准

### 6.1 功能完整性

- ✅ 11 阶段 AI 自主闭环全覆盖
- ✅ AI 自主决策引擎（FULL/SEMI/ADVISORY 三模式）
- ✅ 回测验证 + Paper→Live 升级路径
- ✅ 投资组合级别决策（Markowitz + Kelly）
- ✅ 风险门禁（VaR + 压力测试不可绕过）
- ✅ TWAP/VWAP 智能执行路由
- ✅ AI 自动周报 + 日报
- ✅ Trading Copilot 人机接口

### 6.2 用户体验

- FULL 模式：**人工日常操作 = 0 步**（纯审计）
- SEMI 模式：核心干预 ≤ 3 步（看通知 → 决定是否撤销）
- 配置修改（自主度 / 风险边界 / 标的池）通过 Copilot 自然语言完成
- Dashboard 实时展示 AI 运行状态

### 6.3 业务指标

- AI 自主决策年化收益率 ≥ SPY（α > 0）
- Paper 策略验证通过率 ≥ 70%（胜率≥55%）
- AI 决策平均置信度 ≥ 65
- TWAP/VWAP 执行滑点 < 0.1%/单
- 熔断触发率 < 5%/月

---

## 7. 路线图

### Phase 1–5: 已完成 ✅
- 核心闭环、AI 决策、实时化、策略库、自适应优化

### Phase 6: 研究基础设施 🚀 V10 当前
- **回测引擎**：事件驱动，Walk-Forward，支持10类股票策略
- **DataHub**：Tiger → Polygon → yfinance 优先级路由
- **Paper Trading 账户隔离**：独立 account_id，模拟/实盘双轨

### Phase 7: AI 自主闭环核心 🚀 V10 核心
- **AI_AUTONOMY_LEVEL 三模式**（FULL / SEMI / ADVISORY）
- **组合级决策**（Markowitz + Kelly + 风险门禁）
- **压力测试**（5个历史情景 + 自定义）
- **Paper→Live 自动升级机制**（回测通过 + PA验证）
- **熔断机制 + 操作撤销**（SEMI 模式30分钟窗口）

### Phase 8: AI 深度升级 🚀 V10 当前
- **Trading Copilot**：对话式人机接口，替代散落的按钮
- **AI 自动周报/日报**：Telegram + 系统内存档
- **决策可解释性**：每笔交易 `reasoning` 字段 + 审计日志
- **AI 模型路由**：deepseek-chat/gpt-4o-mini（轻量）+ deepseek-reasoner/gpt-5.2（复杂）

### Phase 9: 执行精细化 🚀 V10 当前
- **TWAP/VWAP 自动路由**（AI 按订单大小自动选择）
- **期权分析中心**（只读信息工具，不执行）：IV曲面、P/C Ratio、异常成交

### Phase 10: 标的扩展 � V10.1 当前
- **ETF 正式支持**（`STOCK,ETF` 模式）：行业轮动 + CTA 商品策略真正运行
- **港股 & 期权行情统一走 Tiger API**：港股（HK 市场）及期权行情数据优先通过老虎证券 API 获取，与美股股票保持一致的 DataHub 路由策略（Tiger → yfinance fallback），不引入 Futu API
- **Tiger 真实下单（美股 + 港股 + 期权）**：TigerOrderExecutor 完整实现，支持 US / HK 双市场及期权下单，FULL 模式实盘可用
- **FULL 模式完整自主闭环**：无需人工干预，AI 自主完成决策→下单→审计
- **Copilot 执行落地**：止损修改 / TWAP 下单 / 清仓三类指令实际执行
- **Dashboard 真实化**：VaR、宏观风险、执行指标、策略统计全部消除占位符
- **AI 组合级决策**：批量信号统一组合视角决策 + JSON 结构化输出消除 regex
- **Paper→Live 毕业自动化**：定时任务检测 + 自动升级
- **Dashboard WebSocket**：实时增量推送，降低延迟至 5s

### Phase 11: V11 计划 🔜
- 期权执行开启（`STOCK,ETF,OPTION` 全模式）
- 多账户支持
- LLM Fine-tuning 个人交易风格
- 实时 L2 订单簿分析
- 移动端原生 App

---

## 8. V10 新功能 API 速览

### 8.1 自主度控制
```
GET  /api/v1/autonomy/status            — 查询当前自主度和运行状态
PUT  /api/v1/autonomy/level             — 修改自主度级别
POST /api/v1/autonomy/pause             — 立即暂停 AI 自动交易
POST /api/v1/autonomy/resume            — 恢复 AI 自动交易
GET  /api/v1/autonomy/audit-log         — 查询 AI 决策审计日志
POST /api/v1/autonomy/revoke/{exec_id}  — 撤销 AI 执行（SEMI 模式，30分钟内）
```

### 8.2 回测引擎
```
POST /api/v1/backtest/run               — 提交回测任务（异步）
GET  /api/v1/backtest/tasks             — 查询任务列表
GET  /api/v1/backtest/tasks/{id}        — 查询任务状态/进度
GET  /api/v1/backtest/tasks/{id}/report — 获取完整报告
GET  /api/v1/backtest/compare           — 多策略对比（最多5个）
DELETE /api/v1/backtest/tasks/{id}      — 删除任务
```

### 8.3 投资组合优化
```
POST /api/v1/portfolio/optimize          — 运行组合优化
GET  /api/v1/portfolio/efficient-frontier — 有效前沿散点
GET  /api/v1/portfolio/risk-contribution  — 各标的风险贡献
POST /api/v1/portfolio/rebalance-plan    — 生成再平衡计划
```

### 8.4 压力测试
```
POST /api/v1/stress-test/run             — 运行压力测试
GET  /api/v1/stress-test/scenarios       — 获取情景库
POST /api/v1/stress-test/custom          — 自定义情景
```

### 8.5 Trading Copilot
```
POST /api/v1/copilot/chat                — 发送消息
GET  /api/v1/copilot/history             — 获取会话历史
DELETE /api/v1/copilot/history           — 清空会话
POST /api/v1/copilot/confirm/{action_id} — 确认指令操作
GET  /api/v1/copilot/morning-brief       — 盘前摘要
GET  /api/v1/copilot/daily-report        — 当日复盘
```

### 8.6 执行算法
```
POST /api/v1/execution/algo/submit       — 提交 TWAP/VWAP 任务
GET  /api/v1/execution/algo/tasks        — 查询任务列表
GET  /api/v1/execution/algo/tasks/{id}   — 查询单任务状态
DELETE /api/v1/execution/algo/tasks/{id} — 取消任务
```

### 8.7 期权分析中心（只读）
```
GET  /api/v1/options/iv-surface/{symbol}     — IV 曲面数据
GET  /api/v1/options/iv-rank/{symbol}        — IV Rank/Percentile
GET  /api/v1/options/unusual-activity        — 异常成交扫描
GET  /api/v1/options/put-call-ratio/{symbol} — P/C Ratio
GET  /api/v1/options/chain/{symbol}          — 期权链报价（只读）
GET  /api/v1/options/expiry-calendar         — 到期日日历
```

### 8.8 Paper Trading
```
GET  /api/v1/paper/status                    — Paper 账户状态
POST /api/v1/paper/reset                     — 重置 Paper 账户
GET  /api/v1/paper/performance               — Paper 账户绩效
GET  /api/v1/paper/graduation-candidates     — 可升级 Live 的策略列表
POST /api/v1/paper/graduate/{strategy_id}    — 手动升级策略到 Live
```

### 8.9 市场体制感知（V10.2-M1）
```
GET  /api/v1/regime/current              — 查询当前体制及置信度
GET  /api/v1/regime/history              — 历史体制记录（分页）
GET  /api/v1/regime/strategy-weights     — 当前体制下各策略权重
POST /api/v1/regime/override             — 人工覆写当前体制（管理员）
```

---

## 附录

### A. 术语表

| 术语 | 定义 |
|------|------|
| Autonomous Alpha Loop | AI 自主完整交易闭环 |
| Risk Gate | 执行前强制风险检验，不可配置关闭 |
| Paper→Live Graduation | 策略经回测+模拟验证后升级实盘的流程 |
| Revoke Window | SEMI 模式下 AI 执行后30分钟内的人工撤销窗口 |
| Circuit Breaker | 单日亏损超阈值时自动暂停 AI 自动交易的熔断机制 |
| Walk-Forward | 滚动训练/测试的回测方法，防止参数过拟合 |
| Alpha | 组合超越 SPY 基准的超额收益 |
| Greeks | 期权风险指标（Delta/Gamma/Vega/Theta），在 STOCK 模式下仅做参考展示 |
| MarketRegime | 当前市场体制（BULL_TREND/BEAR_TREND/HIGH_VOL/MEAN_REVERT/RANGE_BOUND/CRISIS）|
| RegimeClassifier | 五维评分体制分类器，每日 08:00 自动运行，3日连续确认才切换 |
| EventBus | 异步发布/订阅事件总线，解耦体制感知与策略执行模块 |
| StrategyWeightAllocator | 订阅 REGIME_CHANGED 事件并更新 TaskConfig 策略权重的分配器 |
| VaR Multiplier | 体制感知 VaR 门限倍数（危机体制时收紧至 0.5×，牛市趋势时放宽至 1.2×）|
| EarningsFence | 盈利公布前自动激活的仓位上限围栏（默认 50%，可人工覆盖）|
| PositionStateMachine | 仓位全生命周期状态机（INITIAL→PARTIAL→FULL→REDUCING→CLOSED）|
| SignalFusionEngine | 六维加权信号融合引擎，输出 0-100 综合置信度评分 |
| TradeAttributionEngine | 三层 PnL 归因引擎（Alpha源 / 执行质量 / 仓位管理）|
| InsightService | 每周日 AI 自动从历史交易提炼洞察写入知识库的服务 |
| ABTestEngine | A/B 实验管理（scipy t-test 显著性检验，p<0.05 自动结论）|
| DeepResearchEngine | Copilot 多步深度研究引擎（4步推理 → 结构化报告）|

### B. 参考文档

- API.md - 接口文档（V10.2 已含 M2-M8 所有端点）
- BACKEND_DESIGN.md - 后端架构设计（V10.2）
- FRONTEND_DESIGN.md - 前端 UI/UX 设计（V10.2）
- docs/RELEASE_NOTES_V10.2.md - V10.2 完整发布说明
