# V10.4 版本规划 — 巩固、治理与完整性

> **AI量化交易闭环系统** — V10.4 版本规划  
> 文档版本：Draft v1.0 | 制定日期：2026-03-04  
> 基础版本：V10.3.4（2026-03-04 立项归档）  
> 定位：**"不再增加，而是让已有的一切真正运转"——闭合数据断点、治理 UI 债务、夯实自主闭环的实际运行质量**

---

## 0. 产品经理视角诊断

### 0.1 系统全貌复盘（截至 V10.3.3）

| 维度 | 数量 | 趋势 |
|------|------|------|
| 后端服务（`/app/services/`）| **71 个** | ↑ 每版本 +8~15 |
| API 路由模块（`/app/routers/`）| **40 个** | ↑ |
| 数据模型（`/app/models/`）| **37 个** | ↑ |
| 前端页面视图（`/src/views/`）| **47 个** | ↑ 每版本 +5~8 |
| 前端路由数（`/src/router/`）| **48 条** | ↑ |
| 前端 Pinia Store | **18 个** | ↑ |
| PRD 文档行数（PRODUCT.md）| **1271 行** | ↑ 难以维护 |

**趋势诊断**：系统在 V10.0→V10.3.3 的 6 个月内以"功能工厂"模式高速堆砌，每个里程碑都新增大量模块但极少清理旧模块。这在早期是合理的（快速扩展边界），但在当前规模下已导致三类问题。

---

### 0.2 三类系统性问题

#### 问题一：数据管道断点——"建了高速公路但没有车"

最核心的反馈循环链路（**信号 → 执行 → 结果 → 进化**）存在数据空洞：

```
信号生成 → 执行（✅ 正常）
  ↓
成交记录 → TradeJournal（✅ 有数据）
  ↓
actual_return 回填 → TradingSignal（❌ 大量为 null）
  ↓
IC 序列计算（❌ 退化为 fallback，无真实 IC）
  ↓
Alpha Decay / Factor Weights / Calibration（❌ 依赖虚假数据）
  ↓
Kalman 自适应权重更新（❌ 权重未真正自适应）
  ↓
AI 策略进化（❌ 进化闭环实际未闭合）
```

**根因**：`actual_return` 需要在持仓平仓后从成交数据回填到 `TradingSignal`，这个 job 存在（`backfill_journal_prices.py` 等脚本）但**未集成进主调度器**，导致 IC 计算始终拿不到真实标注数据。

**影响范围**：Signal Intelligence Observatory（V10.3.3 旗舰功能）、Adaptive Factor Framework、Confidence Calibration、Decision Post-Mortem 均建立在这个断点之上，呈现为"有界面有服务但数据靠 fallback 撑场"。

---

#### 问题二：UI 债务——"博物馆中的考古遗址"

前端 47 个页面中，至少存在 **5 组已知冗余/重复**：

| 冗余组 | 现有页面 | 问题 |
|--------|---------|------|
| 双仪表盘 | `DashboardPage.vue` + `DashboardV2Page.vue` | 两套并存，用户不知用哪个 |
| 执行类三重奏 | `ExecutionCenter.vue` + `ExecutionListPage.vue` + `AlgoExecutionPage.vue` | 三入口功能重叠，职责模糊 |
| AI 建议二重奏 | `AIAdvisorPage.vue` + `AiAdvicePage.vue` | 命名差一个大写字母，实际可能是同功能的历史遗留 |
| 系统监控四重奏 | `ServiceHealthPage.vue` + `SystemHealthPage.vue` + `SystemMonitorPage.vue` + `ApiMonitoringPage.vue` + `ExternalApiMonitoringPage.vue` | 5个页面监控相似内容 |
| 执行记录双入口 | `ExecutionListPage.vue` + Lifecycle Center 内的 Pipeline | 功能交叉 |

**影响**：
- 新用户认知负担极重，导航分组已有 6 个一级入口
- 维护成本高：修改一个功能需要同步多个文件
- 路由和导航菜单已超过合理认知阈值（48 条路由）

---

#### 问题三：自主循环稳定性——"赛车但轮胎未充满气"

系统设计了完善的 17 阶段自主循环，但运行时存在若干稳定性漏洞：

- **Risk Observability 快照**：需要手动调用 `seed_snapshot_from_live_data` 才有数据，自动调度任务未完全就绪
- **事件日历 2026 年数据**：FOMC/CPI/NFP 硬编码仅到 2025 年底，2026 年数据需补全
- **多 Agent 运行**：`MultiAgentOrchestrator` 创建了框架但 5 个 Agent 是否在每次决策周期真正并行调用 LLM 存疑
- **Post-Mortem 自动触发**：需要 `position_status=CLOSED` 事件，但持仓状态同步到 DB 的链路在某些场景有延迟
- **Smart Alert 聚合**：cosine similarity 去重在没有 embedding model 的情况下退化为简单文本匹配
- **Intelligence Feed WebSocket**：后端推送 endpoint 已定义但前端订阅逻辑的 reconnect 机制需要验证

---

### 0.3 V10.4 核心命题

```
V10.3.3 ："建了高速公路"——功能架构全面完整
V10.4   ："让所有车开起来"——数据真实流动、闭环真正运转、界面真正好用
```

**一句话定位**：
> V10.4 = 数据闭环治理 × UI 大清洗 × 自主循环稳定增强 × 移动触达

---

## 1. V10.4 版本目标与北极星

### 1.1 版本目标

| 目标 | 量化指标 | 当前基准 |
|------|---------|---------|
| 数据完整性 | `TradingSignal.actual_return` 回填率 ≥ 95%（已平仓信号）| 当前 ~0% |
| IC 真实性 | `SignalIntelligenceService` 使用真实 IC（非 fallback）的比例 ≥ 80% | 当前 ~0% |
| UI 精简 | 前端页面总数 ≤ 38（减少 ≥ 9 个）| 当前 47 |
| 导航层级 | 一级导航分组 ≤ 4 个（导航重组）| 当前 6 个 |
| 自主循环健康度 | `AutonomyHealthMonitor` 自检通过率 ≥ 99%/日 | 当前无自检 |
| 移动可用性 | Dashboard + War Room + Copilot 三页面移动端可用（响应式）| 当前无移动支持 |
| 文档可维护性 | PRODUCT.md 拆分为模块化多文件，单文件 ≤ 400 行 | 当前 1271 行 |

### 1.2 V10 系列北极星更新

| 北极星指标 | V10.3 目标 | V10.4 升级目标 |
|-----------|-----------|--------------|
| AI 自主决策收益率 | ≥ SPY 年化 | ≥ SPY + 3% 年化（Sharpe ≥ 0.8）|
| 信号到执行延迟 | < 5s | < 5s（维持，重点提升稳定性）|
| 数据管道完整性 | N/A（未定义）| **actual_return 回填率 ≥ 95%**（新增）|
| 自主循环可用性 | ≥ 99.5% | ≥ 99.5%（+自检心跳 ≥ 99% 通过）|
| UI 认知负担 | N/A | 新用户 <10 分钟找到任意核心功能（可用性测试）|
| LLM 调用成功率 | N/A | ≥ 99%（失败时有优雅降级）|

---

## 2. 里程碑规划（6 个里程碑）

```
M1 数据闭环治理   ─── 2周 ──▶  M2 UI 大清洗      ─── 2周 ──▶  M3 Copilot 主界面升级
                                                                        │
M6 文档重构完成   ◀── 1周 ───  M5 移动触达        ◀── 2周 ───  M4 自主循环稳定增强
```

**总工期预估**：10 周（约 2.5 个月）

---

## 3. M1 — 数据闭环治理（Data Loop Governance）★ 最高优先级

### 3.1 背景

没有真实的 `actual_return` 数据，Signal Intelligence / Calibration / Post-Mortem 等 V10.3.3 的旗舰功能全部依赖 fallback，等于用假数据喂养 AI 进化引擎。**M1 是 V10.4 的地基，其余里程碑的价值建立在 M1 之上。**

### 3.2 核心任务

#### T1.1 — actual_return 自动回填 Job

**当前问题**：`TradingSignal.actual_return` 需手动运行 `backfill_journal_prices.py`，未集成进 APScheduler。

**解决方案**：
- 新增 `ReturnBackfillJob`，在 APScheduler 中注册，**每日盘后 21:30（ET）自动运行**
- 回填逻辑：对每条 `TradingSignal`，通过 `trade_journal` 关联（`symbol + account_id + signal_id` 连接）获取实际成交均价与最终平仓价
- 计算 `actual_return = (exit_price - entry_price) / entry_price`（多头），空头取反
- `pnl_pct` 同步更新
- 回填完成后自动触发 `SignalIntelligenceService.recompute_ic()` 增量更新 IC 序列

**验收**：
- [ ] 每日 21:30 ET 自动运行，日志写入 `scheduler_run_log`
- [ ] 运行后 `TradingSignal.actual_return` 对已平仓信号回填率 ≥ 95%
- [ ] 回填量 > 10 条时自动触发 IC 重算

---

#### T1.2 — IC 序列真实化

**当前问题**：`SignalIntelligenceService.get_signal_intelligence()` 在 `actual_return` 为空时返回 hardcoded fallback 数据，导致 Alpha Decay 界面展示的是假曲线。

**解决方案**：
- 移除 fallback hardcoded IC 数据
- 当样本量 < 10 时，返回 `{"dimension": "...", "ic_5d": null, "sample_count": N, "data_quality": "INSUFFICIENT"}` 状态，前端展示"数据积累中（N/30 天）"占位视图
- 当样本量 ≥ 10 时，计算真实 IC（Pearson 相关系数：预测信号强度 vs 5/20/60日实际收益）
- 新增 `data_quality` 字段：`REAL` / `INSUFFICIENT` / `STALE`（最后更新超 7 日）

**验收**：
- [ ] 移除所有 `fallback` / `mock` IC 数据常量
- [ ] `get_signal_intelligence()` 返回的每个维度包含 `data_quality` 字段
- [ ] 前端 Signal Intelligence 页面在 `data_quality=INSUFFICIENT` 时展示数据积累进度条，不展示虚假曲线

---

#### T1.3 — Risk Observability 快照自动化

**当前问题**：`portfolio_factor_exposure` 快照需要手动调用 `seed_snapshot_from_live_data`，无自动定时写入。

**解决方案**：
- 在 APScheduler 注册 `FactorExposureSnapshotJob`，**每 5 分钟（交易时段）/ 每小时（非交易时段）** 自动运行
- 依赖当前持仓数据（`positions` 表）+ 历史收益率（yfinance/Tiger）做因子回归
- 若持仓为空，写入零快照（`positions_count=0`，各因子 z_score=0），不跳过

**验收**：
- [ ] `portfolio_factor_exposure` 表最新记录时间距当前 ≤ 6 分钟（交易时段内）
- [ ] 无持仓时写入零快照，`Risk Cluster` 页面显示"当前无持仓"而非 loading 空白

---

#### T1.4 — 事件日历 2026 年数据补全

**当前问题**：FOMC/CPI/NFP 硬编码仅覆盖 2025 年，2026 年为空。

**解决方案**：
- 补全 `EventCalendarService` 中 2026 全年 FOMC / CPI / NFP / PCE 硬编码日历
- 新增 `FredApiService` 集成（已有 `fredapi` 依赖），实时拉取下一次 FOMC/CPI 精确日期
- 当 Fred API 不可用时，退化为硬编码 + 告警日志

**已知 2026 年重大事件时间表（预计）**：
```python
FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]
CPI_2026 = [
    "2026-01-15", "2026-02-12", "2026-03-12", "2026-04-10",
    "2026-05-13", "2026-06-11", "2026-07-14", "2026-08-13",
    "2026-09-11", "2026-10-14", "2026-11-13", "2026-12-11",
]
NFP_2026 = [
    "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
    "2026-05-08", "2026-06-05", "2026-07-10", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
]
```

**验收**：
- [ ] `GET /api/v1/events?year=2026` 返回完整的 FOMC/CPI/NFP 事件列表
- [ ] 当前日期起 90 天内的事件均有记录（含盈利日历）
- [ ] EarningsFenceService 对 2026 年盈利日期正常激活围栏

---

#### T1.5 — LLM 调用优雅降级

**当前问题**：LLM API（deepseek/openai）偶发超时或 rate limit，导致依赖 LLM 的服务（Multi-Agent / Post-Mortem / Copilot）直接抛出异常，上游业务中断。

**解决方案**：
- 为所有 LLM 调用封装 `LLMCallGuard`：超时 30s 自动降级，rate limit 后指数退避重试（最多 3 次）
- 降级策略：Multi-Agent 降级为 single-agent 模式；Post-Mortem LLM 失败时跳过但记录 `status=LLM_FAILED`，不阻塞主流程
- 新增 `llm_call_log` 表记录每次调用的 model / latency / tokens / status
- `GET /api/v1/api-monitoring/llm-stats` 返回近 24h 成功率、P95 延迟、总 token 消耗

**验收**：
- [ ] LLM 超时 / 429 不导致业务层 500 返回，降级后返回带 `degraded=true` 标记的响应
- [ ] `llm_call_log` 表记录所有调用，`api_monitoring` 页面实时展示成功率
- [ ] Multi-Agent 决策在 LLM 不可用时退化为规则引擎决策，并在告警中枢写入 `DEGRADED` 事件

---

### 3.3 M1 验收清单

- [ ] T1.1：`actual_return` 回填 Job 上线，每日自动运行，回填率 ≥ 95%
- [ ] T1.2：IC 计算移除所有 fallback 数据，`data_quality` 字段全覆盖
- [ ] T1.3：因子敞口快照每 5 分钟自动写入，无需手动触发
- [ ] T1.4：2026 年 FOMC/CPI/NFP 事件日历完整
- [ ] T1.5：LLM 调用降级机制上线，`llm_call_log` 记录完整

---

## 4. M2 — UI 大清洗（Interface Governance）

### 4.1 背景

前端 47 个页面、6 个导航分组、48 条路由已超出个人用户的合理认知范围。V10.4 将通过**合并冗余页面、重组导航结构、统一视觉规范**将认知负担降低 30%。

### 4.2 页面合并计划

#### 合并方案 A：双仪表盘合并

| 操作 | 详情 |
|------|------|
| 保留 | `DashboardV2Page.vue`（更完整，含体制感知 KPI + 智能告警）|
| 废弃 | `DashboardPage.vue`（旧版，功能已被 V2 全面覆盖）|
| 路由变更 | `/dashboard` → 直接渲染 DashboardV2 内容；`/dashboard-v2` 重定向至 `/dashboard` |
| 迁移注意 | 检查 DashboardV2 是否包含旧版所有 KPI 指标（VaR、宏观风险、策略运行状态）|

#### 合并方案 B：执行类三页合并为一

| 操作 | 详情 |
|------|------|
| 基础页面 | 保留 `IntelligentOrderBookPage.vue`（`/order-book`）作为执行统一入口 |
| 废弃 | `ExecutionCenter.vue` + `ExecutionListPage.vue` |
| 功能归并 | `AlgoExecutionPage.vue`（TWAP/VWAP 任务管理）合并为 Order Book 页的一个 Tab「执行算法队列」|
| 导航更新 | 导航中所有「执行中心」类入口统一指向 `/order-book` |

#### 合并方案 C：AI 建议双页合并

| 操作 | 详情 |
|------|------|
| 保留 | `AIAdvisorPage.vue`（命名更规范）|
| 废弃 | `AiAdvicePage.vue`（确认功能完全重叠后删除）|
| 迁移 | 检查两页面是否存在差异功能，差异功能合并到保留页面 |

#### 合并方案 D：系统监控整合

| 操作 | 详情 |
|------|------|
| 保留 | `SystemMonitorPage.vue`（重命名为系统总览，承载所有监控功能）|
| 废弃 | `ServiceHealthPage.vue` + `SystemHealthPage.vue` |
| 功能分区 | 整合后分为三个 Tab：API 健康 / LLM 监控 / 定时任务 |
| 改造 | `ApiMonitoringPage.vue` 内容迁入「API 健康」Tab；`ExternalApiMonitoringPage.vue` 内容迁入同 Tab的「外部 API」子区块 |

#### 废弃方案 E：遗留功能清理

| 页面 | 操作 | 说明 |
|------|------|------|
| `AiAdvicePage.vue` | 删除 | 确认为 AIAdvisorPage 历史版本 |
| `EtfPoolPage.vue` | 合并至 `StrategiesPage.vue` | ETF 标的池是策略配置的一部分 |
| `TaskManagementPage.vue` | 合并至新版系统监控 Tab | 定时任务管理应在系统监控下 |

**清理后页面目标**：≤ 38 个（减少 9 个页面）

---

### 4.3 导航重组

**当前 6 个一级分组 → 重组为 4 个**：

```
V10.3.3 导航（6 组）              V10.4 导航（4 组）
──────────────────────────       ──────────────────────────
🤖 AI 自主中枢（5项）           ●  首页仪表盘（Dashboard）
🔭 交易可观测性（5项）   ──▶    ●  交易中枢（5 个核心入口）
🧬 AI 中枢（4项）               ●  研究 & 分析（6 项）
🖥️ 指挥室（4项）                ●  AI 洞察 & 系统（6 项）
核心功能（5项）
研究与分析（7项）
复盘 & 进化（3项）
系统（1项）
```

**新导航结构详细设计**：

```
● 首页仪表盘
    └── Dashboard（合并后，默认首页）

● 交易中枢  ← V10.4 核心聚焦区
    ├── 🖥️ 指挥室（War Room）★ 可全屏启动
    ├── 📋 智能订单簿（Order Book） ← 执行三合一入口
    ├── 🔄 交易生命周期（Trade Lifecycle）
    ├── 💬 Trading Copilot ← 悬浮全局入口（任意页面可唤起）
    └── 📅 事件日历（Events）

● 研究 & 分析
    ├── 🌊 市场体制（Regime）
    ├── 📐 组合优化（Portfolio）
    ├── 🔬 回测中心（Backtest）
    ├── 🛡️ 压力测试（Stress Test）
    ├── 📊 期权分析（Options）← 只读
    └── 🌡️ 宏观分析（Macro）

● AI 洞察 & 系统
    ├── 🔬 可观测性中心（Observability Hub）← 三合一：执行/信号/风险
    ├── 🧬 AI 中枢（AI Hub）← 四合一：Agent/校准/因子/剖析
    ├── 📊 归因分析（Attribution）
    ├── 🧪 AI 进化（Evolution）
    ├── 📈 持仓评估（Positions）
    └── ⚙️ 系统（合并后系统监控）
```

---

### 4.4 M2 验收清单

- [ ] 合并 DashboardPage → DashboardV2（路由无感知跳转）
- [ ] 合并执行三页为 Order Book + 执行算法 Tab
- [ ] 合并 AI 建议双页为一
- [ ] 合并系统监控五页为三 Tab 一页
- [ ] 前端路由数 ≤ 40 条（减少 ≥ 8 条）
- [ ] 导航分组调整为 4 个一级分组
- [ ] 所有废弃页面的路由保留 301 重定向，不产生 404

---

## 5. M3 — Copilot 跃升为主交互界面（Copilot UX Supremacy）

### 5.1 背景与设计原则

当前 Copilot 是一个独立页面（`/copilot`），用户需要导航过去才能使用。但产品愿景是"Trading Copilot 是人工唯一主动交互入口"。V10.4 的 M3 将**把 Copilot 变成一个始终可触达的全局能力**。

**设计原则**：
1. **无需离开当前页面**：Cmd+K（Mac）/ Ctrl+K（Win）任意页面唤起 Copilot 浮层
2. **上下文感知**：Copilot 知道用户当前在哪个页面，自动附带上下文（如在 Order Book 页，Copilot 默认知道当前持仓状态）
3. **动作可执行**：Copilot 的执行类指令直接触发后端操作，不需要跳转到其他页面

### 5.2 功能设计

#### F3.1 — 全局 Copilot 浮窗

- 所有页面右下角常驻 Copilot 图标按钮（直径 52px，浮层按钮）
- 点击 / 快捷键 `Cmd+K` 展开浮动会话窗（宽 420px，高 600px，右下角锚定，不遮挡主内容）
- 快捷键 `` ` ``（反引号）在 War Room 全屏模式下唤起（文档已定义）
- Escape 关闭浮窗，会话历史保留

**浮窗 UX 设计**：
```
┌─────────────────────────────────────────┐
│ 💬 Trading Copilot                [×]   │
│ 📍 当前页面：智能订单簿            [全屏]│
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ 已为您加载上下文：                  │ │
│ │ • 活跃持仓 7 笔，浮盈 +$3,420      │ │
│ │ • MSFT 明日财报🔒                  │ │
│ │ • 当前体制：BULL_TREND 85%         │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ [消息历史区域，滚动...]                  │
│                                         │
├─────────────────────────────────────────┤
│ [快捷操作] 盘前摘要  今日复盘  持仓概况 │
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ 输入问题或指令...            [发送]  │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

#### F3.2 — 页面上下文注入

每个主要页面向 Copilot 注入**标准化上下文对象**，格式：

```typescript
interface CopilotPageContext {
  page: string           // 当前页面名称
  active_symbols: string[]  // 当前页面关注的标的
  key_metrics: Record<string, number | string>  // 关键指标
  available_actions: string[]  // 本页可执行操作列表
}
```

| 页面 | 自动注入上下文示例 |
|------|---------|
| Order Book | `{active_symbols: ["AAPL", "NVDA"], key_metrics: {pnl: +3420, high_risk: "MSFT"}}` |
| Risk Cluster | `{key_metrics: {var: "2.4%", es: "3.1%", corr_alert: true}}` |
| War Room | `{key_metrics: {total_pnl: +3420, regime: "BULL_TREND"}}` |

#### F3.3 — 快捷操作面板

Copilot 浮窗底部展示**根据当前页面动态生成的快捷操作**：

| 当前页面 | 快捷操作 |
|---------|---------|
| 任意页面 | 盘前摘要 / 今日复盘 / 持仓概况 |
| Order Book | 修改 {symbol} 止损 / 暂停 {symbol} / 清仓 {symbol} |
| Risk Cluster | 解释当前风险 / 降险建议 / 对冲建议 |
| Regime | 当前体制分析 / 策略权重调整建议 |

#### F3.4 — Copilot 知识图谱扩展

为 Copilot 的 System Prompt 添加**系统状态实时注入**片段（每次调用时动态构建）：

```
当前系统状态（{timestamp}）：
- 自主模式：{autonomy_level}，{running_status}
- 市场体制：{regime}（置信度 {confidence}%）
- VaR 水位：{var_pct}%（上限 {var_limit}%）
- 活跃持仓：{position_count} 笔，总浮盈 {total_pnl}
- 近 24h 执行：{executed_count} 笔，成功率 {success_rate}%
- 最新告警：{alert_summary}
```

**验收**：
- [ ] 全局 Copilot 浮窗在所有路由页面可用，快捷键 Cmd+K 可打开
- [ ] 浮窗展示当前页面上下文摘要（≤5条关键信息）
- [ ] 至少 5 个核心页面实现页面上下文注入
- [ ] 快捷操作按钮根据当前页面动态渲染
- [ ] Copilot System Prompt 包含实时系统状态注入
- [ ] 原 `/copilot` 独立页面保留为"完整对话历史"入口

---

## 6. M4 — 自主循环稳定增强（Autonomous Loop Hardening）

### 6.1 核心目标

保证 AI 自主交易闭环在 7×24 无人值守情况下稳定运行，任何单点故障不导致全局中断，且所有异常均可自动恢复或发出可操作告警。

### 6.2 功能设计

#### F4.1 — 自主循环健康监控（Autonomy Health Monitor）

新增 `AutonomyHealthMonitorService`，每 10 分钟执行一次自检，检查以下关键指标：

```python
class HealthCheckItem:
    name: str
    check_fn: Callable  # 返回 HealthCheckResult
    severity: str       # CRITICAL / WARNING / INFO
    auto_recover: bool  # 是否支持自动恢复

HEALTH_CHECKS = [
    HealthCheckItem("数据库连接", check_db_connection, "CRITICAL", auto_recover=True),
    HealthCheckItem("Redis 连接", check_redis, "CRITICAL", auto_recover=True),
    HealthCheckItem("Tiger API 连通性", check_tiger_api, "WARNING", auto_recover=False),
    HealthCheckItem("定时任务存活", check_scheduler_jobs, "CRITICAL", auto_recover=True),
    HealthCheckItem("actual_return 回填时效", check_return_backfill_freshness, "WARNING", auto_recover=False),
    HealthCheckItem("因子快照时效", check_factor_snapshot_freshness, "WARNING", auto_recover=True),
    HealthCheckItem("LLM API 可达性", check_llm_api, "WARNING", auto_recover=False),
    HealthCheckItem("WebSocket 推送存活", check_ws_broadcast, "INFO", auto_recover=True),
]
```

**自检结果**：写入 `system_health_snapshot` 表，`GET /api/v1/system/health` 返回最新状态。
**告警触发**：CRITICAL 级别失败 → 写入 Smart Alert Center（CRITICAL 优先级，需立即处理）。

#### F4.2 — 定时任务保活与自动重启

- APScheduler 所有 Job 加入 `heartbeat_job_registry`，记录最后运行时间
- 新增 `JobWatchdogJob`（每 15 分钟检查）：若某 Job 超过 2× 预期间隔未运行，自动重新注册并补跑
- 捕获 Job 异常：失败的 Job 写入 `scheduler_run_log(status=FAILED, error=...)`，3 次失败后触发 CRITICAL 告警

#### F4.3 — 多 Agent 协作实际化

**当前问题考证**：`multi_agent_orchestrator.py` 是否已真正协调 5 个 Agent 并行 LLM 调用？需要验证并补全。

**目标实现**：
- `MultiAgentOrchestrator.run()` 在每次 `autonomous_engine` 决策周期调用时，**真正触发 5 个 Agent 各自向 LLM 发送请求**
- Agent 并发执行（`asyncio.gather`），超时 15s 的 Agent 退化为规则引擎
- `AgentMessage` 全量写入 `agent_communication_log`，包含 `latency_ms` 字段
- `GET /api/v1/ai-hub/agent-runs` 真实返回最近 N 次决策的 5 Agent 通信日志

**每次决策周期的 Agent 任务划分**：

| Agent | 任务 | LLM 调用 |
|-------|------|---------|
| `MarketAnalystAgent` | 分析当前体制 + 宏观信号，输出市场摘要 | deepseek-chat |
| `RiskChallengerAgent` | 对每个 BUY 信号输出反驳理由（`challenge_points`），尝试否定决策 | deepseek-reasoner |
| `ExecutionOptimizerAgent` | 给定信号，建议最优执行算法和时机（TWAP/VWAP/市价） | deepseek-chat |
| `ResearchAgent` | 对目标标的快速基本面扫描，输出关键风险点 | deepseek-chat |
| `OrchestratorAgent` | 综合 4 个 Agent 输出，裁决最终 action + confidence 调整 | deepseek-reasoner |

#### F4.4 — 熔断机制增强

**当前热断路**：单日亏损 ≥ `MAX_DAILY_LOSS_PCT` 触发熔断。

**V10.4 新增**：
- **Cascading Failure 熔断**：连续 3 次决策周期均因风险门禁被拒 → 自动降级为 ADVISORY 模式并告警
- **API 熔断**：Tiger API 连续 3 次超时 → 暂停新开仓，发出 CRITICAL 告警
- **异常价格保护**：检测到明显异常价格（偏离 VWAP > 5%）的信号 → 自动标记 `SUSPICIOUS`，暂缓执行 60s 确认
- 熔断状态机新增 `DEGRADED` 状态（介于 RUNNING 和 HALTED 之间，限制新开仓但允许止损和平仓）

#### F4.5 — WebSocket 连接稳定性

**当前问题**：前端 WebSocket 在 Token 过期或网络抖动后未能自动重连，导致实时推送失效。

**解决方案**：
- 前端 `websocket.ts` store 实现指数退避重连（初始 1s，最大 30s，上限 10 次）
- 重连时自动携带最新 JWT Token
- 重连成功后自动订阅之前的频道并拉取错过的事件（`GET /api/v1/ws/missed-events?since=...`）
- War Room Intelligence Feed 特别处理：断线重连后重新请求最新 50 条事件

**验收**：
- [ ] AutonomyHealthMonitor 每 10 分钟自检，结果写入 `system_health_snapshot`
- [ ] 定时任务 Watchdog 在 Job 超时未运行时自动重触发
- [ ] MultiAgentOrchestrator 在每次决策周期真正并发调用 5 个 Agent LLM，`agent_communication_log` 有记录
- [ ] 三个新熔断条件（级联拒绝/API 超时/异常价格）均有测试覆盖
- [ ] WebSocket 前端指数退避重连，断线后 ≤30s 自动恢复推送

---

## 7. M5 — 移动触达（Mobile Access）

### 7.1 背景

当前系统是纯桌面终端风格，完全无法在手机上使用。但用户在非工作时间（通勤、晚上）需要随时了解持仓状况、告警信息，Copilot 更应该随时可用。

### 7.2 移动化范围（精选三核心页面）

MVP 原则：不做全面移动改造，**只让最高频的 3 个场景在手机上可用**：

| 场景 | 对应页面 | 移动端目标 |
|------|---------|----------|
| **我的位置在哪**（持仓概览）| Dashboard（摘要模式）| 竖屏可见：总 PnL + 活跃持仓列表 + VaR 水位 |
| **有没有紧急事项**（告警查看）| Smart Alert Center | 竖屏可见：告警列表 + 一键标记已读 |
| **问一个问题**（查询）| Copilot 浮层 | 全宽浮层，输入框固定底部，对话自然滚动 |

### 7.3 技术方案

- 不引入新的移动端项目，在现有 Vue 3 项目中使用 CSS 媒体查询 + `v-if` 条件渲染
- 定义三个断点：`mobile(≤768px)` / `tablet(≤1024px)` / `desktop`
- 移动端 Dashboard：单列布局，KPI 卡片叠加展示，图表组件替换为数字摘要
- Copilot 浮窗在移动端：全宽全高浮层（95vw × 80vh），输入框固定在底部

### 7.4 移动预览快捷入口

新增 `pnl://` 深链接协议（iOS Shortcut / Android Intent）：
- `pnl://copilot?q=今日持仓状况` → 直接打开浮层并预填问题
- `pnl://alert` → 直接跳转告警列表

**验收**：
- [ ] Dashboard 竖屏 375px 下：总 PnL、活跃持仓数、VaR 水位可见（无横向滚动）
- [ ] Smart Alert Center 竖屏下可用：列表可滚动，告警条目可标记已读
- [ ] Copilot 浮窗在竖屏下可用：输入框固定底部，对话历史可滚动
- [ ] 三核心场景在 iPhone SE（375px）下无横向溢出

---

## 8. M6 — 文档重构与 PRD 可维护性

### 8.1 背景

`PRODUCT.md` 已达 1271 行，`FRONTEND_DESIGN.md` 达 2611 行，单文件已严重影响可维护性。V10.4 将 PRD 拆分为模块化多文件结构，并建立清晰的版本变更管理规范。

### 8.2 文档新架构

```
docs/
├── PRODUCT.md                     # 主文档（≤300行）：愿景 + 北极星 + 功能架构索引
├── product/
│   ├── 01_autonomy_engine.md      # AI 自主决策引擎详述
│   ├── 02_signal_fusion.md        # 信号融合与因子框架
│   ├── 03_risk_gate.md            # 风险门禁与熔断机制
│   ├── 04_execution.md            # 执行算法（TWAP/VWAP/智能路由）
│   ├── 05_observability.md        # 可观测性 2.0（执行/信号/风险三集群）
│   ├── 06_ai_hub.md               # AI 中枢 2.0（多 Agent/校准/因子/剖析）
│   ├── 07_war_room.md             # 指挥室（War Room + Intelligence Feed）
│   ├── 08_copilot.md              # Trading Copilot（能力 + 安全边界）
│   └── 09_api_reference.md        # 完整 API 速览
└── archived/                      # 历史版本归档（已完成）
    └── v10/
        ├── v10.1/ ... v10.4/
```

### 8.3 PRODUCT.md 主文档结构（目标 ≤300行）

主文档只保留：
1. **产品愿景**（1 段）
2. **自主闭环架构图**（1 个ASCII图）
3. **北极星指标表**（1 张表）
4. **功能模块索引**（链接到 `product/0X_xxx.md`）
5. **当前版本验收清单**（仅当前版本的 checklist）
6. **历史版本变更摘要**（各版本一行描述，详情归档到 `archived/`）

**验收**：
- [ ] `PRODUCT.md` 主文档拆分完成，主文件 ≤ 300 行
- [ ] 所有 product/ 子文档创建完毕，内容对应正确
- [ ] `FRONTEND_DESIGN.md` 同步拆分（目标主文件 ≤ 400 行）
- [ ] 历史版本变更摘要保留在主文档，详情在 `archived/` 可检索

---

## 9. 技术债务专项治理

### 9.1 已知技术债务清单

| 债务项 | 位置 | 优先级 | V10.4 处理方式 |
|--------|------|--------|--------------|
| `actual_return` 回填依赖手动脚本 | `scripts/backfill_journal_prices.py` | P0 | M1 集成进 scheduler |
| IC 计算 fallback 硬编码 | `signal_intelligence_service.py` | P0 | M1 移除 |
| FOMC/CPI 2025 年硬编码未更新 | `event_calendar_service.py` | P0 | M1 补全 2026 年 |
| Dashboard 双版本并存 | `DashboardPage.vue` + `DashboardV2Page.vue` | P1 | M2 合并 |
| 执行类入口三重奏 | ExecutionCenter/List/Algo | P1 | M2 合并 |
| LLM 调用无降级机制 | 所有 LLM 调用点 | P1 | M1 封装 LLMCallGuard |
| WebSocket 无重连机制 | `websocket.ts` | P1 | M4 修复 |
| Risk Observability 快照无自动 job | `risk_observability_service.py` | P1 | M1 集成 |
| Multi-Agent 5 Agent 是否真实并发存疑 | `multi_agent_orchestrator.py` | P2 | M4 验证并修复 |
| Smart Alert cosine 相似度无 embedding | `smart_alert_service.py` | P2 | M4 升级为 TF-IDF |
| Post-Mortem 触发链路延迟 | `decision_post_mortem_service.py` | P2 | M4 加异步事件监听 |
| 系统监控五页碎片化 | 5 个监控页面 | P2 | M2 整合为 1 页三 Tab |
| PRD 单文件 1271 行 | `docs/PRODUCT.md` | P3 | M6 拆分 |

### 9.2 新增技术规范

- **LLM 调用**：所有 LLM 调用必须通过 `LLMCallGuard` 包装，禁止裸调用 `ai_client`
- **Scheduler Job**：所有新 Job 必须注册到 `heartbeat_job_registry`，并实现 `idempotent=True`
- **前端页面**：新增页面必须同时实现移动断点样式（≥ 375px 可用）
- **数据质量**：返回可观测性类数据时，必须携带 `data_quality` 字段（`REAL`/`INSUFFICIENT`/`STALE`）

---

## 10. V10.4 验收标准总表

### M1 — 数据闭环治理

| 编号 | 验收项 | 优先级 |
|------|--------|--------|
| 1.1 | `actual_return` 每日 21:30 ET 自动回填，已平仓信号回填率 ≥ 95% | P0 |
| 1.2 | IC 计算无 hardcoded fallback，`data_quality` 字段全覆盖 | P0 |
| 1.3 | `portfolio_factor_exposure` 快照每 5 分钟自动写入（交易时段）| P0 |
| 1.4 | 2026 年 FOMC/CPI/NFP/PCE 完整归档，事件日历 `year=2026` 返回正确 | P0 |
| 1.5 | LLM 超时/429 不导致 500，`llm_call_log` 记录全量调用 | P1 |

### M2 — UI 大清洗

| 编号 | 验收项 | 优先级 |
|------|--------|--------|
| 2.1 | 前端页面总数 ≤ 38，路由总数 ≤ 40 | P1 |
| 2.2 | 废弃路由均有 301 重定向，无 404 | P1 |
| 2.3 | 导航分组 ≤ 4 个，新用户可在 10min 内找到任意核心功能 | P1 |
| 2.4 | 执行类三页合并，Order Book 承载 TWAP/VWAP 任务 Tab | P1 |
| 2.5 | 系统监控整合为单页三 Tab | P2 |

### M3 — Copilot 全局化

| 编号 | 验收项 | 优先级 |
|------|--------|--------|
| 3.1 | 所有页面右下角 Copilot 浮按钮可用，Cmd+K 唤起 | P1 |
| 3.2 | 5 个核心页面实现上下文注入（Dashboard/OrderBook/RiskCluster/WarRoom/Regime）| P1 |
| 3.3 | 快捷操作按钮根据当前页面动态渲染，至少 3 个直接执行类操作 | P2 |
| 3.4 | Copilot System Prompt 含实时系统状态（体制/VaR/持仓/告警）| P1 |

### M4 — 循环稳定性

| 编号 | 验收项 | 优先级 |
|------|--------|--------|
| 4.1 | `AutonomyHealthMonitor` 每 10 分钟自检，结果写入 `system_health_snapshot` | P1 |
| 4.2 | Job Watchdog 在 Job 超时 2× 间隔后自动重注册并补跑 | P1 |
| 4.3 | `MultiAgentOrchestrator` 真实并发调用 5 Agent，`agent_communication_log` 可查 | P2 |
| 4.4 | 三个新熔断条件均实现且有单元测试覆盖 | P1 |
| 4.5 | WebSocket 前端指数退避重连，断线 ≤30s 恢复 | P1 |

### M5 — 移动触达

| 编号 | 验收项 | 优先级 |
|------|--------|--------|
| 5.1 | Dashboard 在 375px 竖屏下无横向溢出，PnL/持仓/VaR 可见 | P2 |
| 5.2 | Smart Alert 在 375px 下可用，可滚动列表，可标记已读 | P2 |
| 5.3 | Copilot 浮层在 375px 下全宽显示，输入框固定底部 | P2 |

### M6 — 文档重构

| 编号 | 验收项 | 优先级 |
|------|--------|--------|
| 6.1 | `PRODUCT.md` 主文档 ≤ 300 行，拆分为 9 个子文档 | P3 |
| 6.2 | `FRONTEND_DESIGN.md` 主文档 ≤ 400 行 | P3 |
| 6.3 | 所有链接有效，`archived/` 历史版本可检索 | P3 |

---

## 11. 北极星指标（V10.4 新增 / 更新）

| 指标 | V10.3 值 | V10.4 目标 |
|------|---------|-----------|
| actual_return 回填率 | **~0%**（手动触发）| **≥ 95%**（自动化）|
| IC 数据质量 | INSUFFICIENT（fallback）| **≥ 80% REAL** |
| 前端路由数 | 48 | **≤ 40** |
| 导航一级分组数 | 6 | **≤ 4** |
| 自主循环日健康自检通过率 | 无测量 | **≥ 99%** |
| LLM 调用成功率 | 无测量 | **≥ 99%** |
| WebSocket 断线恢复时间 | 无测量 | **≤ 30s** |
| Copilot 全局可达性 | 仅 `/copilot` 页 | **所有页面（Cmd+K）** |

---

## 12. 不在 V10.4 范围内（Phase 13 继续持仓）

以下功能延续至 V11 规划，V10.4 不做启动：

- 期权执行开启（`STOCK,ETF,OPTION` 全模式实盘）
- 多账户多用户支持
- LLM Fine-tuning 个人交易风格适配
- 实时 L2 订单簿分析（深度数据接入）
- 原生移动 App（iOS/Android Native）
- 多经纪商接入（非 Tiger）
- 社交分享 / 策略市场
