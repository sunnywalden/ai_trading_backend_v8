<!-- 源自 docs/PRODUCT.md §4.X V10.2-M2~M7 新增功能详述 + §4.Y V10.3 新增功能详述 -->

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


## 4.Z V10.3.2~V10.3.4 迭代功能详述

### 4.Z.1 V10.3.2 — 幂等执行稳定性 & 市场全量池

**幂等执行稳定性**（V10.3.2 核心）：
- 同一 `account_id + signal_id + symbol + action` 重复触发时，仅首个 execution intent 入库成功，后续被幂等拒绝，杜绝重复下单
- 自主执行链路包含完整状态流转：`PENDING → EXECUTING → SUCCESS/FAILED`，以及 `SKIPPED/REJECTED` 分支
- 风控拒绝可观测：RiskGate/CircuitBreaker 拒绝分支同样写入 `autonomous_execution_intent(status=REJECTED)`
- `HOLD/qty<=0` 不再标记为 `EXECUTED`，改为 `SKIPPED`，Dashboard 信号管道增加 `skipped_count`

**市场全量池状态视图**：
- 新增 `/market-universe/status` 视图，展示标的同步进度与数据覆盖率
- 标的池管理入口（`ETFWatchlistPanel`）支持 ETF 流动性筛选
- 港股持仓视图升级：Tiger API 统一美股/港股，标的卡显示市场标签（US/HK）

### 4.Z.2 V10.3.3 — 可观测性 2.0 + AI 中枢 2.0 + 指挥室

#### 可观测性 2.0（Observability 2.0）

**Execution Microscope（执行显微镜）**：
- Implementation Shortfall 四分解：`delay_cost + market_impact_cost + opportunity_cost + timing_cost`，每笔 intent 完成后写入 `execution_quality_log`
- 执行 Alpha 衡量：到达价 vs 实际成交价偏差，按时段×标的热力图可视化
- Dashboard 执行质量面板：实时 P95 滑点指标、Fill Rate 时段分布

**Signal Intelligence Observatory（信号情报观察站）**：
- IC 滚动序列维护：近5/20/60日，推断 `alpha_halflife_days`（alpha 半衰期）
- 六维因子相关矩阵（滚动60日）；Crowding Score > 0.75 时自动降低该维度融合权重
- `/signal-watchtower` 路由：漏斗实时流向图、拒绝信号列表、幽灵交易追踪、参数调优面板

**Risk Observability Cluster（风险可观测集群）**：
- 实时计算五因子敞口（Market / HML / SMB / MOM / QMJ），频率 5分钟/次
- 期望损失 ES@97.5% 实时仪表；相关性骤升 > `CORRELATION_SPIKE_THRESHOLD=0.65` 触发告警

#### AI 中枢 2.0（AI Hub 2.0）

**Multi-Agent Orchestration（五智能体协作）**：
- `MarketAnalystAgent / RiskChallengerAgent / ExecutionOptimizerAgent / ResearchAgent / OrchestratorAgent` 协作
- 结构化 `AgentMessage(agent_id, role, content, confidence, timestamp)` 传递，全量写入 `agent_communication_log`
- `RiskChallengerAgent` 必须对每个 BUY 信号输出反驳理由（`challenge_points: list[str]`）

**AI Confidence Calibration（置信度校准）**：
- 每日 08:15 运行：`[confidence_bucket → actual_win_rate]` 映射，计算 Brier Score 和 ECE
- ECE > 0.12 时自动叠加 `calibration_adjustment_factor`（向 0.5 收敛）

**Adaptive Factor Framework（自适应因子框架）**：
- Kalman Filter 在线权重更新（Q=0.001, R=0.01），每日收盘后执行
- 因子动量加成：近20日 IC 前两名 +5%，末位 -5%，权重历史写入 `signal_weight_history`

**Decision Post-Mortem Engine（决策事后剖析）**：
- 持仓完全平仓后自动触发 `deepseek-reasoner` 生成结构化复盘
- 包含：`factual_summary / counterfactual_buy / counterfactual_hold / counterfactual_sell / key_lessons / improvement_suggestions`
- 自动提炼 1 条 LESSON 型洞察推入 `ai_insight_repository`（`source=POST_MORTEM`）

#### 指挥室（War Room Dashboard）

**War Room Mode（全屏六格指挥视图）**：
- `/war-room` 路由，全屏 6 面板可配置网格（P&L Ticker / Intelligence Feed / Portfolio Heatmap / Risk Gauges / Signal Pulse / Execution Queue）
- 实时 P&L Ticker（5秒推送）：`total_pnl, pnl_change_1h, top_contributor, vs_spy_alpha`
- 全局键盘快捷键：`W` 进入 War Room / `Esc` 退出 / 数字键 1-6 聚焦面板

**Intelligence Feed（AI 情报流）**：
- 聚合 Agent 决策摘要 / 告警 / 事件日历倒计时 / 因子异常 / Copilot 主动推送
- 按 `urgency_score`（0-100）排序；WebSocket 实时推送新事件

**Smart Alert Center（智能告警）**：
- AI 分级（CRITICAL/HIGH/MEDIUM/LOW）+ 相似告警聚合（cosine similarity > 0.85 合并）
- 三种处理状态：READ / IGNORED / ACTION_TAKEN，采纳行动触发 Copilot confirm 流程

### 4.Z.3 V10.3.4 — 冷启动稳态 + 事件日历自动化 + PostMortem 升级

- **冷启动占位视图**：Dashboard / MultiAgentPage / ExecutionMicroscopePage / CalibrationPage 在零数据时展示引导占位，而非空白/404 抖动
- **PostMortem Page 升级**：从手工输入升级为交易选择驱动——选择历史交易 → 自动触发 LLM 事后剖析
- **事件日历自动化**：`post_mortem_jobs.py` EventBus + Cron 自动化，修复日历 freshness 丢失问题，去重修复（排除重复展示）
- **告警面板多账户兼容**：多账户 ID 归因兼容修复

---

## 4.AA V10.4 新增功能详述

### 4.AA.1 V10.4.1 — 数据闭环治理 + Copilot 上下文服务

**数据闭环治理（M1）**：
- `ReturnBackfillJob`（每日 21:30 ET）：自动回填 `TradingSignal.actual_return`，已平仓信号回填率 ≥ 95%，触发 IC 增量重算
- IC `data_quality` 字段全覆盖：`REAL / INSUFFICIENT / STALE`，移除 expected_return 代理收益
- 因子敞口零快照：无持仓时写入 `positions_count=0` 快照，不跳过
- `LLMCallGuard`（超时30s + 指数退避重试 + 降级返回 `degraded=true`）；`LlmCallLog` 表全量记录 model/latency/tokens/status

**Copilot 上下文服务（M3）**：
- `GET /api/v1/copilot/context` 返回当前系统快照（体制/持仓/信号/风控状态），供 Copilot 浮层注入上下文

**自主循环稳定（M4）**：
- `AutonomyHealthMonitorService`（10分钟8项自检）：信号漏斗工作状态、持仓同步、风控门禁可达性等
- `JobWatchdog`（Job 超时2x触发补跑），防止调度任务静默失败

### 4.AA.2 V10.4.2 — 信号精英化（五层漏斗 + 幽灵交易）

**五层信号漏斗（SignalQualityFunnel）**：

| 层 | 过滤规则 |
|----|---------|
| Layer 0 | 宇宙过滤：标的池白名单 + 黑名单检查 |
| Layer 1 | 体制门控：当前 Regime 是否允许该策略信号 |
| Layer 2 | 组合预检：MAX_CONCURRENT_POSITIONS / MAX_DAILY_SIGNALS 硬约束 |
| Layer 3 | 多维共振：tech/fundamental 对立或 CRISIS 做多 → conviction 强制归零 |
| Layer 4 | 置信度校准门：SignalConvictionScorer 输出 LOW/MEDIUM/HIGH/ELITE 质量标签 |

**SignalConvictionScorer 评分公式**：
```
conviction = composite×0.4 + resonance_bonus×0.25 + regime_alignment×0.15 + historical_ic×0.1 + timing_quality×0.1
```

**幽灵交易（Ghost Trade）**：
- Layer 3/4 拒绝的信号自动创建虚拟跟踪记录，每日价格更新
- 计算幽灵胜率 vs 实际胜率对比，量化"拒绝的代价"
- `ghost_trade_jobs.py` 每日收盘后更新幽灵 PnL；新增 DB 表：`signal_quality_audit_logs / ghost_trades`

**ELITE 信号**：仅豁免 Layer 2 的 `MAX_DAILY_SIGNALS` 检查，不豁免仓位/相关性/RiskGate

### 4.AA.3 V10.4.3 — 风险降低优先执行 + 系统监控增强

**减仓/平仓快速通道**：
- `RiskGateService.check(..., signal_intent=...)` 识别 `REDUCE/EXIT/STOP_LOSS_EXIT/FORCE_EXIT`，豁免日交易笔数 / VaR / 压力测试检查
- `ALLOW_CLOSING_DURING_CIRCUIT_BREAKER=true`：熔断期间保留平仓通道
- `AutonomousEngine` 三种执行路径：`STANDARD / FAST_CLOSE / FORCE_EXIT`；关闭类信号跳过 `SignalQualityFunnel`；`force_exit=true` 进一步跳过冷却与 Redis 锁
- `SignalPositionFilter`：超持仓的 `REDUCE` 自动升级为 `EXIT`
- `OrderExecutor`：`EXIT/REDUCE` 使用实际持仓数量，允许港股 odd-lot 退出

**系统监控增强**：
- `/system` 页新增三大视图：交易生命周期监测（17阶段 Plan/Position FSM）、主要数据流转状态、模块与细粒度服务状态
- 新增 API：`/api/v1/system-monitor/lifecycle`、`/api/v1/system-monitor/data-flows`、`/api/v1/system-monitor/services`

---

## 4.AB V10.5.1 新增功能详述——机构级研究与交易操作台

> 核心主题：从"功能完整"走向"机构级交易操作系统"——把现有 observability 资产重组为可解释、可审计、可晋级的研究与交易操作台。一级导航仍维持 4 组，信息架构坚持"决策级可视化而非页面膨胀"。

### 4.AB.1 Alpha Truth Stack（/alpha-lab）

**Strategy Scorecard 2.0**：
- 每个策略展示四层收益口径：Gross Return / Net Return / After-Cost Return / After-Turnover Return
- 分体制（BULL/BEAR/SIDEWAYS/VOLATILE）的收益分解
- Shadow False-Reject 视图：可观测由信号漏斗误拒的潜在 alpha
- IC 来源标注（`REAL / INSUFFICIENT / STALE`），Alpha 衰减曲线按 Regime / Capacity Bucket 分组

### 4.AB.2 Portfolio Construction 2.0（/portfolio）

**Portfolio Construction Console（升级版）**：
- Risk Budget Tab：各标的风险预算使用率、预算剩余可用量
- Marginal Contribution Tab：Alpha / Risk / Turnover / Liquidity 四维边际贡献矩阵
- Liquidity Usage Tab：标的流动性评分、日均成交额与仓位规模匹配度

### 4.AB.3 Execution Policy Engine（/execution-policy）

- **Execution Policy Snapshot**：当前生效的执行策略参数快照（algo / timing / size / urgency）
- **Pre-Trade Cost 估算**：每笔信号进入 Engine 前计算预估冲击成本
- **Child-Order Timeline**：大单拆分后子订单执行进度时间轴
- **Child-Order Replay**：历史执行路径重现与质量评估

### 4.AB.4 Governance Pipeline（/governance/pipeline）

- Discovery → Paper → Shadow Live → Challenger → Production 五阶段证据链
- 每阶段设定 promotion blockers（最小历史交易笔数、最低胜率、VaR 合规）
- Rollback Reason 记录，支持追溯策略退级原因
- Experiment Ledger：记录每个策略的全生命周期实验历史

### 4.AB.5 Live Safety & Model Degradation Guard

- LLM 降级检测：`degraded=true` 累计超阈值时，自动降低自主度至 ADVISORY
- 数据源切换告警：Tiger API 降级至 yfinance 时推送警告
- 决策延迟监控：AI 决策耗时 P95 告警，防止超时 stale 决策执行

---

## 4.AC V10.5.2 新增功能详述——组合席位竞争引擎

> 核心升级：持仓上限从刚性拒绝规则升级为动态席位分配机制。

### 4.AC.1 Unified Candidate Pool & 准入评分

- 当前持仓 + 新信号统一纳入候选池进行席位竞争
- **统一准入评分公式**：
  ```
  admission_score = alpha_quality - replacement_friction - risk_penalty + regime_fit
  ```
- 满仓时按分数淘汰末位 N 个对象：持仓 → `EXIT/FORCE_EXIT`，信号 → `REJECTED_BY_CAPACITY_REPLACEMENT`

### 4.AC.2 替换保护机制（防止过度翻仓）

| 参数 | 说明 |
|------|------|
| `MIN_REPLACEMENT_EDGE_BPS` | 最小替换优势（基点），低于则不替换 |
| `MAX_REPLACEMENTS_PER_CYCLE` | 每轮最多替换数量 |
| `MIN_HOLD_MINUTES_BEFORE_REPLACEMENT` | 持仓最短持有时间门槛 |
| `REPLACEMENT_COOLDOWN_MINUTES` | 同标的替换冷却期 |

**Incumbent Decay Model**：持仓持续参与席位竞争，质量衰减由 `PositionScoringService` 动态评估

### 4.AC.3 审计与治理

- `capacity_decision_audit_log` 表：全量记录候选评分、淘汰原因、保护带触发结果
- `CAPACITY_REPLACEMENT_DRY_RUN` 模式：先观测排名变化，不实际执行替换
- Feature flags：`CAPACITY_REPLACEMENT_ENABLED / DRY_RUN / MAX_PER_CYCLE / MIN_EDGE`

### 4.AC.4 前端可视化

- `/portfolio` 新增席位竞争看板 Tab（候选排名列表、淘汰清单、评分拆解 tooltip）
- `/autonomy` 新增 CapacityArbiter 状态卡（本轮候选数、触发次数、替换成功/拒绝计数、dry-run 徽章）
- `/order-book` 新增 `REJECTED_BY_CAPACITY_REPLACEMENT` 拒绝原因详情抽屉
- `/capacity-arbiter` 新路由：Preview 模拟面板 + Audit Log 历史 + Config 治理参数面板

---

## 4.AD V11.0.1 新增功能详述——Capital Intelligence & Autonomous Evolution OS

> 核心主题：在不放宽既有风控上限的前提下，让系统知道哪里被卡住、为什么被卡住、如何更快释放资本并生成改进动作。

### 4.AD.1 Capital Velocity

- `ConvictionFrictionTracker` 跟踪近命中开仓信号的摩擦积累状态
- `SignalQualityFunnel` 在 feature flag 开启时可依据摩擦状态进行 soft-relief 判定
- `GrossExposureAllocator` 引入闲置资本感知，避免“有现金却长期 no-headroom”导致的静默阻断

### 4.AD.2 Self-Perception

- `MetaStateSnapshotService` 聚合系统元状态快照
- `False-Hold Alerts` 暴露“应减未减、持续压制”的持仓问题
- `/autonomy` 页面可直接展示摩擦积累、False-Hold 与系统阻断总览

### 4.AD.3 Improvement Lab

- `ImprovementCandidateService` 自动生成参数/模块级改进候选
- 候选以结构化字段返回：类型、目标模块、目标参数、建议值、证据摘要、验证计划、状态

### 4.AD.4 Governance

- 所有 V11.0.1 增量能力均受独立 feature flag 控制
- 当前对外文档只声明已实现的 `/api/v1/autonomy/*` 端点，不扩写未落地接口
