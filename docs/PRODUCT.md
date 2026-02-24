# 产品需求文档 (PRD)

> **AI量化交易闭环系统** - 个人美港股智能交易平台  
> 版本：V10.0 | 更新日期：2026-02-24  
> 变更摘要：**AI 自主闭环**升级——AI 默认自主完成建议→决策→交易→回测→优化完整流程，人工以审计、干预、配置角色参与；新增回测引擎、DataHub 多数据源、投资组合优化、压力测试、Trading Copilot、TWAP/VWAP、Paper Trading 账户隔离、AI 周报；**默认仅支持股票标的，期权等衍生品通过配置开启**

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

### 3.1 AI 自主交易闭环（11 阶段）

```
① Market Scan（市场扫描）
    ↓ DataHub 多源行情 + 宏观风险实时评估
② Research（研究分析）
    ↓ 12大类策略并行扫描 + AI 多维评分
③ Signal Generation（信号生成）
    ↓ 信号引擎聚合，AI 决定候选标的
④ Portfolio Decision（组合决策）★ V10 新增
    ↓ Markowitz/风险平价/Kelly 最优仓位计算
⑤ Risk Gate（风险门禁）★ V10 新增
    ↓ VaR/CVaR 检查 + 压力测试通过后放行
⑥ Execution（智能执行）
    ↓ 小单直接下单 / 大单 TWAP/VWAP 拆分
⑦ Monitoring（持续监控）
    ↓ 实时跟踪 + 止损/止盈自动触发
⑧ Evaluation（绩效评估）
    ↓ 每日 PnL 归因 + Alpha/Beta 分解
⑨ Backtest Validation（回测验证）★ V10 新增
    ↓ 策略参数变更前先跑 Walk-Forward 回测
⑩ Adaptive Optimization（自适应优化）
    ↓ AI 自动调整策略权重 + 参数
⑪ Loop（自主循环）
    → 回到 ① 持续进化，无需人工介入
```

**人工在哪里？**
- 初始化：设定风险预算、标的池、自主度等级
- 运行中：通过 Copilot 随时查询，重大操作（SEMI 模式）收通知可撤销
- 复盘：查看 AI 自动生成的周报，调整边界配置

### 3.2 核心模块

#### A. 数据与研究层
- **DataHub 多数据源聚合**：Tiger（实时）→ Polygon.io → yfinance → Redis 缓存，优先级路由
- **市场热点分析**：识别热门赛道和个股
- **宏观风险评分**：地缘政治 + 经济指标综合判断
- **技术面分析**：多指标技术分析（AI 自主触发）
- **基本面分析**：估值 + 成长性评估

#### B. AI 决策层（V10 核心升级）
- **策略库**：12大类量化策略（股票模式下跳过期权策略）
- **组合智能**：Markowitz + 风险平价 + Kelly，从单标的决策升级为组合视角
- **AI 自主决策引擎**：deepseek-reasoner / gpt-5.2 驱动，自主完成建议→决策全流程
- **风险门禁**：VaR/CVaR + 压力测试，双重把关，AI 不绕过

#### C. 执行层
- **智能执行路由**：小单市价 → 大单 TWAP/VWAP 自动选择
- **Paper/Live 双轨**：新策略先走 Paper，回测通过后升级 Live
- **止损/止盈引擎**：AI 动态更新止损位（追踪止损）

#### D. 监控与复盘层
- **价格告警**：条件触发，AI 自动评估是否需要干预
- **AI 自动复盘**：交易日志自动填写，AI 生成质量评估
- **AI 周报**：每周日自动推送 Telegram，全面覆盖收益/策略/行为三个维度
- **行为评分**：对 AI 自身决策质量打分（替代人类行为评分）

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

# 数据源
DATA_HUB_PRIMARY=tiger           # tiger / polygon / yfinance
DATA_HUB_FALLBACK=polygon,yfinance

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

### Phase 10: 标的扩展 🔜 V11 计划
- ETF 轮动策略（`STOCK,ETF` 模式）
- 期权执行开启（`STOCK,ETF,OPTION` 模式）
- 港股全面支持（Futu API）

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
| G reeks | 期权风险指标（Delta/Gamma/Vega/Theta），在 STOCK 模式下仅做参考展示 |

### B. 参考文档

- API.md - 接口文档
- BACKEND_DESIGN.md - 后端架构设计
- FRONTEND_DESIGN.md - 前端 UI/UX 设计
