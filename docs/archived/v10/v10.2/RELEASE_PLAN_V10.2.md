# V10.2 版本规划

> **AI量化交易闭环系统** — V10.2 版本规划  
> 文档版本：Draft v1.0 | 制定日期：2026-02-27  
> 基础版本：V10.1（2026-02-26 立项）  
> 定位：**从"自动执行"到"自主进化"——构建具有自我学习、市场适应与完整闭环管理能力的 AI 自主交易大脑**

---

## 0. 规划背景

### 0.1 V10.1 能力基线

V10.1 完成了"执行闭环打通"的核心目标：Tiger 真实下单、Telegram 通知、Copilot 指令落地、Dashboard 真实化，并将 AI 决策升级为组合级视角。至此，系统已具备：

```
市场扫描 → 信号生成 → 组合决策 → 风险门禁 → 自动执行 → 持仓监控 → AI复盘
```

**V10.1 能力天花板**：上述闭环是"静态"的——策略参数不会因市场变化自动调整，仓位管理是"一次性"的（开仓后无系统性加减仓逻辑），AI 复盘停留在描述层面（发现问题但不自动改进），市场体制（趋势/震荡/高波动）对策略选择无感知。

### 0.2 V10.2 核心命题

> "如果 V10.1 是一位严格执行指令的交易员，那么 V10.2 要成为一位能感知市场、动态管理头寸、从每笔交易中学习并持续进化的顶级投资组合经理。"

**三大跃升目标**：

| 维度 | V10.1 状态 | V10.2 目标 |
|------|-----------|-----------|
| **市场感知** | 静态策略权重 | 动态感知市场体制，实时调整策略组合 |
| **仓位管理** | 开仓即定尺寸 | 全生命周期动态管理（加仓/减仓/移动止损/分批出场） |
| **自我进化** | 复盘描述问题 | 从盈亏中自动提炼规则，闭环改进信号与参数 |

### 0.3 V10.2 定位一句话

```
V10.2 = 市场体制感知 × 动态仓位管理 × AI 自我进化闭环
```

---

## 1. 总体架构升级：完整自主交易大脑

### 1.1 升级后的 AI 自主闭环（17 阶段）

```
┌─────────────────────────────────────────────────────────────────────┐
│                    V10.2 AI 自主交易大脑（全天候运行）                  │
│                                                                       │
│  ① 宏观 & 市场体制感知（NEW）                                           │
│      ↓  体制标签：TREND / RANGE / HIGH_VOL / CRISIS                    │
│  ② 策略组合动态调权（NEW）—— 体制驱动，非手动                            │
│      ↓  策略池权重矩阵实时重分配                                         │
│  ③ 多维信号融合（ENHANCED）—— 技术+基本面+另类数据                       │
│      ↓  信号置信度矩阵                                                   │
│  ④ 事件感知层（NEW）—— 财报/分红/宏观日历驱动                            │
│      ↓  事件风险加权                                                     │
│  ⑤ 组合级 AI 决策（ENHANCED）—— 全局视角 + 相关性                       │
│      ↓  开仓尺寸 + 加仓计划 + 出场矩阵                                   │
│  ⑥ 风险门禁（保留）—— VaR + 压力测试，不可绕过                           │
│      ↓                                                                  │
│  ⑦ 智能执行（ENHANCED）—— TWAP/VWAP + 执行时机优化                     │
│      ↓                                                                  │
│  ⑧ 开仓后持续监控（NEW）—— 多维跟踪，信号衰减检测                        │
│      ↓                                                                  │
│  ⑨ 动态仓位调整引擎（NEW）—— 加仓/减仓/移动止损                         │
│      ↓  置信度上升→加仓，逻辑失效→减仓/平仓                              │
│ ⑩ 分批出场引擎（NEW）—— 根据目标达成/信号衰减分批兑现                    │
│      ↓                                                                  │
│ ⑪ 逐笔交易绩效归因（ENHANCED）—— 多因子精细归因                         │
│      ↓  α来源、timing、sizing 三维评价                                    │
│ ⑫ AI 复盘与规律提炼（NEW）—— 从盈亏中蒸馏可操作规则                      │
│      ↓  自动生成"经验库"条目                                             │
│ ⑬ 策略参数自适应（ENHANCED）—— 结合体制 + 历史规律自动调参               │
│      ↓                                                                  │
│ ⑭ 信号模型微调（NEW）—— 用真实盈亏标注历史信号数据                       │
│      ↓  离线精调 → AB测试 → 替换主模型                                   │
│ ⑮ 回测验证（保留）—— Walk-Forward，策略升级前置                          │
│      ↓                                                                  │
│ ⑯ Paper→Live 自动毕业（V10.1）                                          │
│      ↓                                                                  │
│ ⑰ 自主循环（持续进化）→ 回到①                                           │
│                                                                         │
│  [人工层] 设定边界 / Copilot 查询 / 审计日志 / 随时干预                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 模块间联动总线设计

V10.2 引入**事件总线（EventBus）**，各模块通过发布/订阅解耦：

```
事件类型（Topic）              生产者 → 消费者
────────────────────────────────────────────────────────────
REGIME_CHANGED               体制感知 → 策略调权、风险门禁
SIGNAL_CONFIDENCE_UPDATED    信号融合 → 动态仓位引擎
EVENT_CALENDAR_ALERT         事件感知 → 风险门禁、执行引擎
POSITION_PNL_UPDATED         持仓监控 → 动态仓位引擎
CLOSE_SIGNAL_TRIGGERED       动态仓位 → 分批出场引擎
TRADE_CLOSED                 出场引擎 → 归因引擎、AI 复盘
INSIGHT_GENERATED            AI 复盘  → 经验库、策略参数优化
STRATEGY_PARAMS_UPDATED      参数优化 → 回测验证、策略引擎
```

---

## 2. 七大核心功能模块

---

### 模块一：智能市场体制感知引擎（Market Regime Intelligence）

**战略意义**（华尔街私募视角）：顶级 CTA 基金的核心差异化在于不同市场体制下动态调整敞口——趋势市用动量，震荡市用均值回归，高波动市收缩仓位，危机时切换防御。V10.1 策略权重是静态配置，等同于用同一把武器应对所有战局。

#### 2.1.1 体制识别器（RegimeClassifier）

**识别维度**（5 维综合打分）：

| 维度 | 算法 | 权重 |
|------|------|------|
| **价格趋势强度** | 200日 ADX + Hurst 指数 | 30% |
| **波动率体制** | HMM（隐马尔可夫模型）基于 VIX/RVOL | 25% |
| **宏观周期位置** | 美债收益率曲线斜率 + ISM PMI 分位数 | 25% |
| **市场微观结构** | 换手率、涨跌停板比例、做空量比 | 10% |
| **跨资产信号** | 美债 vs 美股相关性极性、黄金 vs 风险资产 | 10% |

**体制标签枚举**：
```python
class MarketRegime(Enum):
    BULL_TREND      = "强趋势牛市"   # ADX>25, 价格 > MA200, 低 VIX
    BEAR_TREND      = "强趋势熊市"   # ADX>25, 价格 < MA200, 高 VIX
    SIDEWAYS_BULL   = "震荡偏多"     # ADX<20, 价格 > MA200
    SIDEWAYS_BEAR   = "震荡偏空"     # ADX<20, 价格 < MA200
    HIGH_VOLATILITY = "高波动体制"   # VIX > 25, 无方向确认
    CRISIS          = "危机模式"     # VIX > 40 or 宏观风险评分 > 85
```

**体制持久性机制**：防止噪音频繁切换，采用"3日确认规则"——连续 3 个交易日信号一致方更新体制标签。

#### 2.1.2 策略动态调权（StrategyWeightAllocator）

每次体制变更，自动重计算策略权重矩阵：

```python
REGIME_STRATEGY_WEIGHTS = {
    MarketRegime.BULL_TREND: {
        "momentum_breakout":     0.30,   # 趋势市主力
        "golden_cross":          0.25,
        "factor_momentum_quality":0.20,
        "mean_reversion":        0.05,   # 趋势市抑制均值回归
        "low_volatility":        0.10,
        "sector_rotation":       0.10,
    },
    MarketRegime.SIDEWAYS_BULL: {
        "bollinger_mean_reversion":0.35, # 震荡市主力
        "pairs_trading":          0.25,
        "low_volatility":         0.20,
        "momentum_breakout":      0.10,  # 震荡市降低动量权重
        "sector_rotation":        0.10,
    },
    MarketRegime.HIGH_VOLATILITY: {
        "low_volatility":         0.40,  # 高波动期防御
        "sector_rotation":        0.20,  # 防御性行业
        "bollinger_mean_reversion":0.20,
        "pairs_trading":          0.20,
        # 动量策略权重变 0，不追涨杀跌
    },
    MarketRegime.CRISIS: {
        "low_volatility":         0.60,
        "sector_rotation":        0.40,  # 完全防御，现金+公债
        # 所有其他策略权重为 0，仅持有防御仓位或现金
    },
}
```

**与现有系统联动**：
- 体制变更事件 → `autonomous_engine` 重新拉取 `REGIME_STRATEGY_WEIGHTS`
- 体制变更事件 → `risk_gate_service` 自动调整 `MAX_VAR_PCT`（CRISIS 体制时降为 1.5%）
- 体制写入 `autonomy_audit_log.regime_at_decision`，供复盘归因

**新增 API**：
```
GET  /api/v1/regime/current           — 当前体制标签 + 置信度 + 切换历史
GET  /api/v1/regime/history           — 历史体制分布（用于复盘）
GET  /api/v1/regime/strategy-weights  — 当前体制下各策略权重
```

---

### 模块二：动态仓位全生命周期管理引擎（Dynamic Position Lifecycle）

**战略意义**（顶级交易员视角）：职业交易员与散户最大区别不是"选股"，而是"仓位管理"——何时加仓（conviction 增强时）、何时减仓（信号衰减时）、止损如何随价格移动、如何分批兑现利润。V10.1 开仓后只有静态止损，缺乏系统性的全周期管理。

#### 2.2.1 持仓状态机（PositionStateMachine）

```
[ENTERING]
   ↓ 首批入场完成（如 50% 目标仓位）
[SCALING_IN] ←─── 加仓条件触发
   ↓ 达到目标仓位 or 时间阈值
[HELD]
   ├── 减仓条件触发 → [SCALING_OUT]
   ├── 信号完全失效 → [EXITING_FULL]
   └── 止损触发 → [STOP_LOSS_EXIT]
[SCALING_OUT]
   ↓ 部分平仓
[HELD] or [CLOSED]
[CLOSED]
```

#### 2.2.2 加仓引擎（ScaleInEngine）

**加仓触发条件**（满足任意一条，且 VaR 门禁通过）：

| 触发信号 | 说明 | 加仓比例 |
|---------|------|---------|
| AI 置信度从开仓时 **+10pp** | 信号进一步验证 | +25% 目标仓位 |
| 价格突破开仓后关键阻力 | 趋势确认 | +20% 目标仓位 |
| 新增独立策略信号共振（≥2策略同向） | 多策略共振加仓 | +15% 目标仓位 |
| 组合相关性降低（该标的降低整体相关） | 分散化贡献增加 | +10% 目标仓位 |

**加仓价格保护**：每次加仓后`average_cost`更新，止损位随之升至新的合理支撑位（不降低止损）。

#### 2.2.3 减仓与移动止损引擎（ScaleOutEngine + TrailingStop）

**减仓触发条件**（优先级排序）：

```python
SCALE_OUT_RULES = [
    # 优先级 1：止损（程序化，立即执行）
    Rule("STOP_LOSS", when="price ≤ stop_loss_price", action="close_100%"),

    # 优先级 2：AI 信号衰减（置信度跌幅 > 20pp 且持仓盈利时先锁利）
    Rule("SIGNAL_DECAY", when="confidence_delta < -20pp AND unrealized_pnl > 0",
         action="close_50%, move_stop_to_breakeven"),

    # 优先级 3：策略逻辑失效（该信号来源策略评分 < 40）
    Rule("THESIS_BROKEN", when="signal_source_score < 40",
         action="close_75%, full_exit_if_no_secondary_signal"),

    # 优先级 4：时间止损（持仓超 N 日但无盈利）
    Rule("TIME_STOP", when="holding_days > MAX_HOLD_DAYS AND unrealized_pnl < 0",
         action="close_100%"),

    # 优先级 5：目标价分批兑现
    Rule("TARGET_HIT_PARTIAL", when="price ≥ take_profit_1", action="close_33%"),
    Rule("TARGET_HIT_FULL",    when="price ≥ take_profit_2", action="close_remaining"),
]
```

**追踪止损（Trailing Stop）**：
```python
class TrailingStopEngine:
    """持仓盈利超过 R:R 1:1 后启用追踪止损"""

    def update(self, position: Position, current_price: float) -> float:
        if position.unrealized_pnl_ratio >= 0.01:  # 1% 浮盈
            trail_pct = self._get_trail_pct(regime=current_regime)
            # 追踪止损只能上移，不能下移
            new_stop = current_price * (1 - trail_pct)
            return max(new_stop, position.current_stop_loss)
        return position.current_stop_loss

    def _get_trail_pct(self, regime: MarketRegime) -> float:
        return {
            MarketRegime.BULL_TREND: 0.05,       # 趋势市宽止损，让利润奔跑
            MarketRegime.HIGH_VOLATILITY: 0.03,  # 高波动市收紧
            MarketRegime.CRISIS: 0.02,           # 危机模式极紧
        }.get(regime, 0.04)
```

**新增 API**：
```
GET  /api/v1/positions/{id}/lifecycle     — 持仓生命周期状态 + 事件流水
POST /api/v1/positions/{id}/manual-scale  — 人工触发加减仓（Copilot 指令落地）
GET  /api/v1/positions/scale-in-candidates — 当前可加仓标的列表（AI 打分 + 权限）
```

---

### 模块三：事件驱动交易引擎（Event-Driven Trading Engine）

**战略意义**（量化 PM 视角）：事件驱动策略（财报、分红、指数调整、宏观数据公布）在统计上提供超额 Alpha，但执行窗口极短。V10.1 无事件感知层，AI 可能在财报前1天重仓进入高风险区。

#### 2.3.1 事件日历（EventCalendar）

**事件类型与数据源**：

| 事件类型 | 数据源 | 风险方向 | 默认行动 |
|----------|--------|---------|---------|
| **财报公布（EPS Date）** | yfinance earnings calendar + Tiger | 高风险 | 财报前 1 日减仓至 50%；财报后根据 vs 预期结果重新开仓 |
| **美联储 FOMC 会议** | FRED calendar | 中高风险 | FOMC 前 1 日降低总敞口至 70%，宏观风险权重 +15% |
| **月度非农 / CPI / PCE** | FRED calendar | 中风险 | 数据公布前2小时切换到低波动权重 |
| **标普500指数成分调整** | SPDR announcement | 正向事件 | 纳入标的提前建仓（套利窗口） |
| **股息除权日** | Tiger dividend calendar | 对持仓影响 | 自动调整成本基准，复权处理 |

#### 2.3.2 财报围栏（EarningsFence）

```python
class EarningsFenceService:
    """财报事件围栏：自动管理财报前的风险敞口"""

    PREEARNING_DAYS = 1      # 财报前 N 个交易日触发
    PREEARNING_SIZE_LIMIT = 0.5   # 不超过正常仓位的 50%

    async def apply_fence(self, symbol: str, account_id: str):
        earnings_date = await self._get_next_earnings(symbol)
        days_to_earnings = trading_days_between(today, earnings_date)

        if days_to_earnings <= self.PREEARNING_DAYS:
            position = await position_service.get(symbol, account_id)
            if position and position.size_pct > self.PREEARNING_SIZE_LIMIT:
                # 自动减仓至 50%，等财报后重新评估
                await scale_out_engine.execute(position, target_pct=0.5,
                    reason="EARNINGS_FENCE", notify=True)

    async def post_earnings_evaluation(self, symbol: str, actual_eps: float,
                                        consensus_eps: float):
        """财报公布后 AI 评估：超预期则考虑加仓，不及预期则减仓/平仓"""
        beat_ratio = (actual_eps - consensus_eps) / abs(consensus_eps)
        event_context = {"beat_ratio": beat_ratio, "symbol": symbol}
        # 推送给 autonomous_engine 重新决策
        await event_bus.publish("EARNINGS_RESULT", event_context)
```

#### 2.3.3 事件与现有模块联动

```
事件日历定时任务（每日 07:00）
    → 扫描未来 5 个交易日所有持仓相关事件
    → 生成"事件风险地图"
    → 推送到 autonomous_engine（纳入决策上下文）
    → 触发相应围栏（EarningsFence / MacroFence）
    → Telegram 推送事件提醒（SEMI/ADVISORY 模式）
```

**新增 API**：
```
GET  /api/v1/events/calendar          — 未来 N 日事件日历（含持仓相关标记）
GET  /api/v1/events/earnings-fence    — 当前处于财报围栏中的持仓列表
POST /api/v1/events/override-fence    — 人工覆盖围栏（二次确认）
```

---

### 模块四：多维信号融合引擎（Multi-Signal Fusion Engine）

**战略意义**（华尔街私募视角）：顶级量化基金的 Alpha 来自"信号正交性"——不同维度的信号如果相互印证，置信度乘数提升；如果相互矛盾，AI 应该不交易或减小仓位，而非仓促决策。V10.1 的信号评分机制相对单一。

#### 2.4.1 信号置信度矩阵

**6维信号 → 置信度矩阵**：

| 维度 | 信号来源 | 权重 | V10.1 状态 |
|------|---------|------|-----------|
| **技术面** | 均线、动量、布林带、RSI | 25% | ✅ 已有 |
| **基本面** | PE/ROE/增速、质量因子 | 20% | ✅ 已有 |
| **宏观因子** | PMI、利率曲线、VIX | 15% | ✅ 已有 |
| **量价异常** | 成交量突增、大宗交易 | 15% | ⚠️ 基础版 |
| **期权市场信号（只读）** | IV Rank、P/C Ratio、异常买权 | 15% | ✅ 已有（只读） |
| **市场情绪** | 做空比例、散户情绪、新闻情感 | 10% | ❌ 新增 |

#### 2.4.2 信号冲突检测与置信度折扣

```python
class SignalFusionEngine:
    def compute_fused_confidence(self, signal_vector: dict) -> FusedSignal:
        # 1. 加权基础分
        base_score = sum(
            signal_vector[dim]["score"] * weight
            for dim, weight in DIMENSION_WEIGHTS.items()
        )

        # 2. 信号共振加成（多维同向 → 乘数提升）
        aligned_dims = [d for d in signal_vector if signal_vector[d]["direction"] == "BULLISH"]
        resonance_bonus = (len(aligned_dims) - 3) * 0.05 if len(aligned_dims) > 3 else 0

        # 3. 信号冲突折扣（技术 vs 基本面方向相反时降低置信）
        conflict_penalty = 0
        if signal_vector["technical"]["direction"] != signal_vector["fundamental"]["direction"]:
            conflict_penalty = 0.15   # 关键维度冲突，折扣 15%

        # 4. 体制一致性修正
        regime_multiplier = REGIME_CONFIDENCE_MULTIPLIER[current_regime]

        final_confidence = (base_score + resonance_bonus - conflict_penalty) * regime_multiplier
        return FusedSignal(
            confidence=min(final_confidence, 95),
            conflict_detected=(conflict_penalty > 0),
            dominant_signal=self._get_dominant_dimension(signal_vector),
        )
```

#### 2.4.3 市场情绪信号（新增第6维）

| 情绪指标 | 数据来源 | 更新频率 |
|---------|---------|---------|
| 做空利率（Short Interest Ratio） | 聚合公开数据 | 每周 |
| 散户情绪指数（Retail Sentiment） | StockTwits/Reddit 情感分析（AI）| 每日 |
| 新闻情感分数（News Sentiment） | 主流财经 RSS + AI 摘要评分 | 实时 |
| 内部人交易信号（Insider Activity） | SEC Form 4 公开数据 | 每日 |

**情感 AI 分析**：使用 `deepseek-chat` 对财经新闻标题批量情感分类（BULLISH/NEUTRAL/BEARISH），输出 `[-1, 1]` 情感指数。成本低（轻量模型），每日运行一次。

---

### 模块五：AI 交易复盘与自我进化引擎（AI Self-Learning Loop）

**战略意义**（量化 PM 视角）：最好的量化系统不是写死规则，而是能从交易结果中自动学习——哪类信号在哪种体制下更准确、哪个策略在哪个市值段表现更好、AI 的过度自信何时出现。这是 V10.2 最核心的差异化。

#### 2.5.1 逐笔交易精细归因（Trade Attribution Engine）

每笔交易平仓后自动触发31维归因分析（`TradeAttributionEngine`）：

**三层归因结构**：

```
① Alpha 来源归因
   ├── 策略贡献（该信号来自哪个策略，策略层面 Alpha）
   ├── 体制匹配分（开仓时体制 vs 该策略适合的体制的匹配度）
   └── 信号先导性（比价格行动领先了几个交易日）

② 执行质量归因
   ├── 入场 timing 评分（入场价 vs 当日 VWAP）
   ├── 出场 timing 评分（出场价 vs 当日 VWAP）
   ├── 加减仓操作贡献（对比"固定仓位假设"的超额收益）
   └── 滑点成本拖累

③ 仓位管理归因
   ├── 初始尺寸是否合理（Kelly 建议 vs 实际）
   ├── 追踪止损是否过早触发
   └── 是否错过了加仓机会（AI 信号曾上升但未触发加仓）
```

#### 2.5.2 AI 经验库（InsightRepository）

**智能复盘 Prompt（deepseek-reasoner）**：

每周批量分析最近N笔已平仓交易的归因数据，提炼可复用规律：

```python
WEEKLY_INSIGHT_PROMPT = """
你是一位顶级量化交易研究员，请分析以下 {n} 笔交易的三层归因数据，提炼：
1. 【模式发现】：哪些信号组合在哪种市场体制下有显著正 Alpha
2. 【陷阱发现】：哪些信号组合在哪种体制下反复亏损（应避免或减重）
3. 【执行改进】：入场/出场 timing 有何系统性偏差
4. 【参数建议】：基于统计，给出 2-3 条具体的策略参数调整建议

输出格式要求（严格 JSON）：
{
    "patterns": [{"pattern": "...", "regime": "...", "confidence": 0.x, "sample_n": n}],
    "traps": [{"trap": "...", "regime": "...", "loss_rate": 0.x}],
    "execution_improvements": [{"finding": "...", "suggestion": "..."}],
    "parameter_suggestions": [{"strategy": "...", "param": "...", "current": x, "suggested": y, "reason": "..."}]
}
"""
```

**经验库条目（InsightEntry）**：

```sql
CREATE TABLE ai_insight_repository (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    insight_type ENUM('PATTERN', 'TRAP', 'EXECUTION', 'PARAM_SUGGESTION'),
    regime VARCHAR(32),                      -- 适用体制
    strategy_name VARCHAR(64),               -- 关联策略
    content TEXT NOT NULL,                   -- 自然语言描述
    actionable_rule JSON,                    -- 可自动执行的规则（JSON）
    confidence DECIMAL(4,2),                 -- AI 对该经验的置信度
    sample_count INT DEFAULT 0,              -- 支撑该经验的样本量
    validated BOOLEAN DEFAULT FALSE,         -- 是否经回测验证
    applied_count INT DEFAULT 0,             -- 被系统采纳应用次数
    win_rate_impact DECIMAL(5,2) NULL,       -- 应用后胜率变化（验证后填入）
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_validated_at DATETIME NULL
);
```

#### 2.5.3 参数自动试验框架（AutoParameterExperiment）

经验库中置信度 > 0.7 的参数建议，自动进入 A/B 试验流程：

```
経験库建议: "布林带均值回归在 BULL_TREND 体制下止损应从 2σ 收紧至 1.5σ"
    ↓
自动创建策略 Fork（布林带_v2，参数修改，其余不变）
    ↓
Paper 账户双轨运行（v1 vs v2）2周
    ↓
统计显著性检验（t-test，p < 0.05）
    ↓
通过 → 替换 v1 参数 + 写入经验库 confirmed = True + Telegram 通知
不通过 → 保留 v1 + 标记该经验 "回测验伪"
```

**与 V10.1 Walk-Forward 的衔接**：AutoParameterExperiment 的 Paper 验证复用 `backtest_service` 和 `paper_trading_service` 已有基础，只需新增 Fork 管理层和统计检验模块。

**新增 API**：
```
GET  /api/v1/insights/repository        — 经验库列表（分类、过滤）
GET  /api/v1/insights/{id}              — 单条经验详情
POST /api/v1/insights/{id}/validate     — 手动触发回测验证
GET  /api/v1/experiments                — 正在进行的 A/B 参数试验
GET  /api/v1/attribution/trades         — 逐笔交易归因报告
GET  /api/v1/attribution/summary        — 归因汇总（策略/体制/执行三层）
```

---

### 模块六：执行质量监控与优化（Transaction Cost Analysis）

**战略意义**（量化 PM 视角）：执行成本是可量化的确定性拖累。顶级机构对每笔交易的 TCA（Transaction Cost Analysis）精细到毫秒级。对个人系统而言，系统性跟踪滑点并发现改进模式是实现净收益提升的最快途径之一。

#### 2.6.1 实时 TCA 流水线

```
订单提交 → 记录 benchmark_price（提交时 VWAP/mid-price）
    ↓
订单成交 → 记录 fill_price + fill_time
    ↓
TCA 计算:
    implementation_shortfall = fill_price - benchmark_price
    market_impact = fill_price - pre_trade_vwap（以 5min VWAP 为基准）
    timing_alpha = benchmark_price - post_trade_vwap_15min（机会成本）
```

#### 2.6.2 执行时机优化器（ExecutionTimingOptimizer）

基于历史成交数据，分析最优执行时段：

```python
class ExecutionTimingOptimizer:
    """基于日内流动性模式，优化 TWAP/VWAP 时间窗口"""

    def recommend_execution_window(self, symbol: str, side: str,
                                   urgency: str) -> ExecutionWindow:
        # 分析该标的历史成交量日内分布（U型曲线特征）
        volume_profile = await self._get_intraday_volume_profile(symbol)

        if urgency == "HIGH":
            return ExecutionWindow(start=0, end=30, algo="MARKET")

        if side == "BUY":
            # 买入避开开盘30分钟（流动性虽好但价差大）
            return ExecutionWindow(start=60, end=150, algo="VWAP",
                                   avoid_windows=["09:30-10:00", "MOC_5min"])
        else:
            # 卖出利用收盘前流动性高峰
            return ExecutionWindow(start=210, end=360, algo="TWAP",
                                   add_moc_slice=True)
```

---

### 模块七：Copilot 升级为 AI 交易助理（Enhanced Trading Copilot）

**战略意义**（交易员视角）：V10.1 Copilot 能执行固定指令。V10.2 升级为真正的"AI 对冲基金合伙人"——能主动汇报、主动预警、能进行高质量的投资讨论，并理解复杂的多步意图。

#### 2.7.1 主动智能（Proactive Intelligence）

Copilot 不再被动等待查询，主动推送以下洞察：

| 主动推送类型 | 触发条件 | 内容 |
|------------|---------|------|
| **市场体制切换预警** | 体制置信度 > 70% 但尚未确认 | "检测到市场体制可能从 BULL_TREND 转向 HIGH_VOL，建议提前降低动量仓位" |
| **加仓机会提醒** | ScaleInEngine 检测到可加仓标的 | "AAPL 置信度从 72 升至 85（+13pp），满足加仓条件，建议加仓 25%" |
| **异常归因预警** | 近5笔同类策略连续亏损 | "布林带策略在当前体制下近5笔均亏损，建议暂停或减权" |
| **周期对比** | 每周一早市前 | "本周 AI 计划：宏观风险 62（中性），重点关注财报季中的 META/GOOG" |

#### 2.7.2 多步意图理解

V10.1 Copilot 处理单步指令。V10.2 支持复合多步：

```
用户："下周有 NVDA 财报，你觉得该怎么处理当前持仓？"

Copilot（多步推理）：
  Step 1: 查询 NVDA 当前持仓（12% 仓位，浮盈 +8.3%）
  Step 2: 查询 NVDA 财报日（3个交易日后）
  Step 3: 分析 IV Rank（当前 78，显著偏高，市场预期大波动）
  Step 4: 查询历史财报后 NVDA 表现（近4次，2次 beat 涨 >10%，2次 miss 跌 >8%）
  Step 5: 生成建议

  AI 回复：
  "NVDA 财报 3 天后（3/2）。当前持仓 12% 浮盈 8.3%。分析：
   - IV Rank 78 偏高，说明市场预期较大波动
   - 近4次财报2涨2跌，不确定性高
   建议（3个选项）：
   A) 保守：减持至 6%（锁定一半利润，保留上涨参与）
   B) 中性：保持 12% 但将止损移至 breakeven（+0%）
   C) 进取：维持仓位，财报后根据结果加减仓
   [执行选项A] [执行选项B] [不操作]"
```

#### 2.7.3 投资研究模式（DeepResearch Mode）

```
用户 Copilot 命令："深度分析 MSFT 当前投资价值"

AI（deepseek-reasoner 驱动，估计 15s）：
  ① 实时拉取技术面数据（Tiger API）
  ② 最新基本面：PE / EPS增速 / FCF Yield（yfinance）
  ③ 期权市场信号：IV Rank / P/C Ratio（只读）
  ④ 与 SPY / QQQ 相关性（组合影响）
  ⑤ 当前体制下该类型标的历史胜率
  ⑥ 生成结构化研究报告（500字 + 关键指标表 + 评级）
  ⑦ 给出"是否适合当前组合"的一句话结论 + 建议仓位
```

---

## 3. 北极星指标 V10.2

| 指标 | V10.1 目标 | V10.2 目标 | 关联模块 |
|------|-----------|-----------|---------|
| AI 决策年化 Alpha vs SPY | > 0 | **≥ +5%** | 市场体制感知 + 信号融合 |
| 平均持仓盈亏比（R:R） | 1:1.5 | **≥ 1:2.0** | 动态仓位管理 |
| 执行滑点（VWAP 偏离） | < 0.1% | **< 0.07%** | TCA 优化 |
| AI 复盘规律提炼准确率 | N/A | **≥ 60% 经验被回测验证** | AI 自我进化 |
| 财报事件围栏触发成功率 | N/A | **100%（零漏检）** | 事件引擎 |
| 体制识别切换准确率（事后） | N/A | **≥ 70%（与 5日后涨跌吻合）** | 体制感知 |
| Copilot 多步意图准确率 | 单步 | **≥ 85%（多步意图理解）** | Copilot 升级 |
| 参数 A/B 试验成功转化率 | N/A | **≥ 40% 建议通过验证升级** | 自我进化 |

---

## 4. 模块联动示意（端到端场景）

### 场景一：市场体制切换驱动全链路联动

```
08:00 定时任务触发 RegimeClassifier
  → 检测到：ADX 从 18 升至 27，RVOL 从 1.2 降至 0.8
  → 体制自 SIDEWAYS_BULL → BULL_TREND（连续3日确认）
  → EventBus.publish("REGIME_CHANGED", {old: SIDEWAYS, new: BULL_TREND})

  ↓ 联动 1：StrategyWeightAllocator
    → 布林带均值回归权重 0.35 → 0.05
    → 动量突破权重 0.10 → 0.30
    → 宏观日志记录体制切换

  ↓ 联动 2：RiskGate
    → MAX_VAR_PCT 从 0.025 调整为 0.035（趋势市可适度增敞口）

  ↓ 联动 3：AutonomousEngine 下次决策循环
    → 拉取新的策略权重矩阵
    → 按动量突破信号优先重新评估当前候选标的

  ↓ 联动 4：DynamicPositionEngine
    → 检查现有持仓中的均值回归策略头寸，若逻辑已不符合新体制
    → 对持有 >5 日的均值回归仓位发起信号失效检查，触发 THESIS_BROKEN 减仓规则

  ↓ 联动 5：Copilot 主动推送
    → Telegram: "市场体制已切换至 BULL_TREND。策略组合已重新调权：
      动量+30%、均值回归-30%。现有均值回归仓位将按信号衰减规则逐步减仓。"
```

### 场景二：财报事件驱动减仓→财报后重建仓

```
财报前 1 日 07:30：EventCalendar 定时扫描
  → 检测 TSMC(TSM) 将于今日盘后发布财报
  → 系统持有 TSM 15%（超过 PREEARNING_SIZE_LIMIT=50%×15%=7.5%）

  ↓ EarningsFenceService.apply_fence()
    → 触发减仓至 7.5%（减 7.5%，TWAP 15分钟执行）
    → reason = "EARNINGS_FENCE"
    → Telegram 推送 + 审计日志

财报发布后（次日 09:30）：
  → yfinance 拉取实际 EPS vs 预期
  → 超预期 +12%，beat_ratio = 0.12（> 0.05 阈值）
  → EventBus.publish("EARNINGS_RESULT", {symbol: TSM, beat_ratio: 0.12})

  ↓ AutonomousEngine 接收事件
    → 重新运行 TSM 六维信号融合（技术面反应 + 基本面改善）
    → 置信度从 68 升至 82
    → 建议恢复仓位至 14%
    → 风险门禁通过
    → TWAP 执行加仓至 14%

  ↓ TradeAttributionEngine 记录
    → 财报围栏操作：减仓 7.5% → 次日回补 14%
    → 实际等于"主动降低财报不确定性风险，财报后确认质量后重建仓"
    → 归因分类：EVENT_DRIVEN 类型
```

### 场景三：AI 经验自动进化闭环

```
周日 22:00 WeeklyInsightJob 触发
  → 拉取本周 28 笔已平仓交易归因数据
  → 发现：布林带策略在当前 BULL_TREND 体制下，7笔，平均 R:R 0.8（低于 1.5 目标）
            技术面信号强（avg 78），但基本面信号弱（avg 42）——两者冲突明显
  → AI deepseek-reasoner 生成 InsightEntry：
      type = "TRAP"
      content = "布林带均值回归在 BULL_TREND 体制下，当基本面信号 < 50 时亏损率高达 71%"
      actionable_rule = {"if": "regime=BULL_TREND AND fundamental_score<50", "then": "skip"}
      confidence = 0.78

  ↓ AutoParameterExperiment.create_experiment()
    → Fork 布林带策略，加入 "fundamental_score<50 → skip" 过滤规则
    → Paper A/B 双轨运行 2 周

  2周后：
    → Paper 数据：新版本布林带 Sharpe 从 0.85 → 1.28，统计显著（p=0.03）
    → 自动替换生产策略参数
    → InsightEntry.validated = True, applied_count + 1
    → Telegram 推送："策略进化通知：布林带策略新增过滤规则（BULL_TREND下基本面<50跳过），
      2周验证 Sharpe +0.43，已自动升级"
```

---

## 5. 技术架构变更

### 5.1 新增服务层

```
app/services/
  ├── regime_classifier.py         # 市场体制识别（HMM + 多维评分）
  ├── regime_strategy_allocator.py # 体制驱动策略权重分配
  ├── event_calendar_service.py    # 事件日历管理（财报/宏观/分红）
  ├── earnings_fence_service.py    # 财报围栏执行
  ├── signal_fusion_engine.py      # 六维信号融合 + 冲突检测
  ├── dynamic_position_engine.py   # 动态仓位全生命周期管理
  ├── scale_in_engine.py           # 加仓引擎
  ├── scale_out_engine.py          # 减仓与分批出场引擎
  ├── trailing_stop_engine.py      # 追踪止损
  ├── trade_attribution_engine.py  # 逐笔 31 维归因
  ├── insight_repository_service.py# AI 经验库管理
  ├── auto_experiment_service.py   # 参数 A/B 试验框架
  ├── tca_service.py               # Transaction Cost Analysis
  ├── execution_timing_optimizer.py# 执行时机优化
  └── sentiment_analyzer_service.py# 新闻/情绪信号分析
```

### 5.2 事件总线

```python
# app/core/event_bus.py（新增）
class EventBus:
    """异步发布/订阅事件总线，解耦模块间联动"""

    _subscribers: dict[str, list[Callable]] = {}

    @classmethod
    def subscribe(cls, topic: str, handler: Callable):
        cls._subscribers.setdefault(topic, []).append(handler)

    @classmethod
    async def publish(cls, topic: str, payload: dict):
        for handler in cls._subscribers.get(topic, []):
            asyncio.create_task(handler(payload))   # 非阻塞
        await audit_log.record_event(topic, payload) # 所有事件记入审计
```

### 5.3 新增数据库表

```sql
-- 市场体制历史
CREATE TABLE market_regimes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    regime VARCHAR(32) NOT NULL,
    confidence DECIMAL(4,2),
    detected_at DATETIME NOT NULL,
    confirmed_at DATETIME NULL,        -- 连续3日确认后填入
    ended_at DATETIME NULL,
    trigger_signals JSON               -- 触发体制切换的具体指标值
);

-- 事件日历
CREATE TABLE event_calendar (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    symbol VARCHAR(32),
    event_type VARCHAR(32),            -- EARNINGS/FOMC/NFP/DIVIDEND/INDEX_REBAL
    event_date DATE NOT NULL,
    event_time TIME NULL,
    consensus_value DECIMAL(10,4) NULL,
    actual_value DECIMAL(10,4) NULL,   -- 发布后填入
    beat_ratio DECIMAL(6,3) NULL,
    ai_reaction_triggered BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 持仓生命周期事件流
CREATE TABLE position_lifecycle_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    position_id BIGINT NOT NULL,
    event_type VARCHAR(32),   -- ENTERED/SCALED_IN/SCALED_OUT/STOP_MOVED/CLOSED
    trigger_reason VARCHAR(64),
    size_before DECIMAL(8,4),
    size_after DECIMAL(8,4),
    price DECIMAL(12,4),
    ai_confidence_at_event DECIMAL(4,2),
    regime_at_event VARCHAR(32),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 交易归因明细
CREATE TABLE trade_attribution_records (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    trade_id BIGINT NOT NULL,
    alpha_source_strategy DECIMAL(6,4),     -- 策略层 Alpha
    alpha_regime_match DECIMAL(6,4),        -- 体制匹配贡献
    alpha_signal_lead_days INT,             -- 信号先导天数
    entry_timing_score DECIMAL(4,2),        -- 入场 timing（0-100）
    exit_timing_score DECIMAL(4,2),         -- 出场 timing
    scale_management_contribution DECIMAL(8,4),  -- 加减仓超额贡献
    slippage_cost DECIMAL(8,4),
    total_pnl DECIMAL(12,4),
    net_alpha DECIMAL(12,4),               -- 剔除 Beta + 成本后的净 Alpha
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- AI 经验库
CREATE TABLE ai_insight_repository (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    insight_type ENUM('PATTERN', 'TRAP', 'EXECUTION', 'PARAM_SUGGESTION'),
    regime VARCHAR(32),
    strategy_name VARCHAR(64),
    content TEXT NOT NULL,
    actionable_rule JSON,
    confidence DECIMAL(4,2),
    sample_count INT DEFAULT 0,
    validated BOOLEAN DEFAULT FALSE,
    applied_count INT DEFAULT 0,
    win_rate_impact DECIMAL(5,2) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_validated_at DATETIME NULL
);

-- 参数 A/B 试验
CREATE TABLE strategy_ab_experiments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    insight_id BIGINT,
    strategy_name VARCHAR(64),
    control_params JSON,               -- 对照组参数（当前生产）
    treatment_params JSON,             -- 实验组参数
    status ENUM('RUNNING', 'COMPLETED', 'REJECTED', 'PROMOTED'),
    paper_account_control_id VARCHAR(64),
    paper_account_treatment_id VARCHAR(64),
    start_date DATE,
    end_date DATE NULL,
    control_sharpe DECIMAL(5,2) NULL,
    treatment_sharpe DECIMAL(5,2) NULL,
    p_value DECIMAL(6,4) NULL,
    result VARCHAR(16) NULL,           -- PROMOTED / REJECTED
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5.4 新增定时任务（APScheduler）

```python
# jobs/v10_2_jobs.py
scheduler.add_job(regime_classifier.run_daily_classification,
    CronTrigger(day_of_week="mon-fri", hour=8, minute=0))

scheduler.add_job(event_calendar_service.scan_upcoming_events,
    CronTrigger(day_of_week="mon-fri", hour=7, minute=30))

scheduler.add_job(dynamic_position_engine.run_lifecycle_check,
    CronTrigger(day_of_week="mon-fri", minute="*/15"))  # 每15分钟

scheduler.add_job(tca_service.compute_daily_tca,
    CronTrigger(day_of_week="mon-fri", hour=16, minute=30))

scheduler.add_job(insight_repository_service.run_weekly_insight_generation,
    CronTrigger(day_of_week="sun", hour=22, minute=0))

scheduler.add_job(auto_experiment_service.check_experiment_completion,
    CronTrigger(day_of_week="mon-fri", hour=23, minute=30))

scheduler.add_job(sentiment_analyzer_service.analyze_daily_news,
    CronTrigger(day_of_week="mon-fri", hour=8, minute=30))
```

---

## 6. 前端变更（V10.2）

| 组件/页面 | 变更类型 | 核心内容 |
|----------|---------|---------|
| `RegimePage.vue`（新增） | 新增 | 市场体制可视化面板：当前体制标签+置信度、5维雷达图、历史体制时间轴、策略权重分布 |
| `PositionLifecyclePage.vue`（新增） | 新增 | 单个持仓生命周期视图：状态机可视化、加减仓事件流水线、追踪止损实时位置、三层归因摘要 |
| `EventCalendarPage.vue`（新增） | 新增 | 事件日历（财报/FOMC/宏观数据），与持仓联动标记风险，事件围栏状态展示 |
| `InsightsPage.vue`（新增） | 新增 | AI 经验库展示：模式/陷阱/建议三分类、经验置信度标签、A/B试验进度、被采纳经验的绩效跟踪 |
| `AttributionPage.vue`（新增） | 新增 | 归因分析中心：逐笔归因明细、策略层/执行层/仓位管理层三维汇总图 |
| `DashboardV2Page.vue` | 增强 | 新增：当前体制标签卡片、信号融合评分热力图、本周 TCA 执行质量、加仓机会徽章 |
| `AutonomyPage.vue` | 增强 | 新增：事件围栏活动列表、参数 A/B 试验跑马灯、近期经验库更新 |
| `CopilotPage.vue` | 增强 | 支持多步意图的进度条显示、主动推送消息的特殊样式（Proactive Badge）、DeepResearch 模式触发按钮 |
| `PositionsPage.vue` | 增强 | 持仓卡片新增：体制匹配度评分、加仓建议标识、信号衰减告警、距财报天数 |

---

## 7. 性能要求（V10.2）

| 指标 | V10.1 目标 | V10.2 目标 |
|------|-----------|-----------|
| 体制识别计算 | N/A | < 2s（含 HMM 推断）|
| 逐笔归因生成 | N/A | < 5s/笔（平仓后异步触发）|
| 周度经验提炼（AI）| N/A | < 120s（deepseek-reasoner 批量）|
| 动态仓位检查（全仓位轮检）| N/A | < 3s（15分钟一次）|
| 信号融合计算（单标的）| < 8s | < 6s（新增两维但优化并行）|
| TCA 日终计算 | N/A | < 10s（全部当日交易）|
| Copilot DeepResearch | N/A | < 20s（单标的完整研究）|

---

## 8. 版本里程碑

| 里程碑 | 目标 | 关键交付物 |
|-------|------|---------|
| **M1：市场体制引擎** | W1-W2 | RegimeClassifier 可运行；体制历史回测吻合度验证；策略调权联动 AutonomousEngine |
| **M2：事件引擎** | W2-W3 | EventCalendar 扫描可用；EarningsFence 在 Paper 账户验证；Telegram 财报围栏通知 |
| **M3：动态仓位管理** | W3-W4 | PositionStateMachine 完整实现；ScaleIn/Out/TrailingStop 在 Paper 验证；联动 RiskGate |
| **M4：信号融合升级** | W4 | 六维信号融合可运行；情绪信号接入；冲突检测折扣生效 |
| **M5：归因引擎** | W4-W5 | TradeAttributionEngine 上线；历史交易补算归因；AttributionPage 前端展示 |
| **M6：AI 自我进化** | W5-W6 | InsightRepository 首次运行；A/B 试验框架可创建/监控；经验库前端展示 |
| **M7：TCA + Copilot 升级** | W6-W7 | TCA 日报上线；Copilot 多步意图 85% 测试覆盖；DeepResearch 模式可用 |
| **版本发布** | W8 | V10.2 全量发布，更新文档；北极星指标基线建立 |

---

## 9. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|-----|------|------|
| HMM 体制识别在少数极端行情误判 | 中 | 中 | 3日确认机制 + 人工覆盖体制标签接口；初期以 SEMI 模式观察 |
| AI 经验提炼产生"虚假规律"（过拟合少量样本） | 高 | 中 | 严格 sample_count ≥ 10 才生成经验；经验创建后强制回测验证才能影响生产 |
| 加仓引擎在高波动期频繁触发增加风险 | 中 | 高 | 加仓必须通过 RiskGate（VaR 门禁）；HIGH_VOL/CRISIS 体制下加仓阈值收紧 +5pp |
| 财报日期数据不准确导致围栏错误触发 | 低 | 中 | 双源核验（yfinance + Tiger）；铃声前1小时再次确认；人工可 override-fence |
| 多个联动模块并发事件导致竞态条件 | 中 | 中 | EventBus 串行化同一 symbol 的消费链；数据库乐观锁保护持仓变更 |
| 参数 A/B 试验周期过短统计不显著 | 中 | 低 | 最少 2 周、最少 10 笔交易才允许结论；p < 0.05 才允许 promote |

---

## 10. 与 V11 边界划定

**V10.2 不做**（规划给 V11）：

| 功能 | 理由 |
|------|------|
| 期权执行（Greeks 对冲、期权策略执行） | V10.2 期权仍为只读信号输入；执行复杂度需 V11 独立模块 |
| 强化学习（RL）策略直接控制下单 | 需要海量真实交易数据积累（V10.2 开始建立数据集，V11 训练）|
| L2 订单簿实时分析与算法交易 | 数据成本高，V10.2 优先用已有数据源提升信号质量 |
| 多账户并行（不同策略匹配不同子账户） | V10.2 完善单账户深度；V11 横向扩展 |
| LLM Fine-tuning 个人交易风格 | V10.2 开始用 InsightRepository 积累标注数据，V11 启动 fine-tuning |

---

## 附录 A：V10.2 新增 API 全览

```
# 市场体制
GET  /api/v1/regime/current
GET  /api/v1/regime/history
GET  /api/v1/regime/strategy-weights
POST /api/v1/regime/override           — 人工覆盖体制标签（需二次确认）

# 事件引擎
GET  /api/v1/events/calendar
GET  /api/v1/events/earnings-fence
POST /api/v1/events/override-fence

# 动态仓位
GET  /api/v1/positions/{id}/lifecycle
POST /api/v1/positions/{id}/manual-scale
GET  /api/v1/positions/scale-in-candidates

# 归因分析
GET  /api/v1/attribution/trades
GET  /api/v1/attribution/summary
GET  /api/v1/attribution/trades/{trade_id}

# AI 经验库
GET  /api/v1/insights/repository
GET  /api/v1/insights/{id}
POST /api/v1/insights/{id}/validate
POST /api/v1/insights/{id}/reject       — 人工否决某条经验

# A/B 试验
GET  /api/v1/experiments
GET  /api/v1/experiments/{id}
POST /api/v1/experiments/{id}/accept    — 人工提前接受实验结果
POST /api/v1/experiments/{id}/reject

# TCA
GET  /api/v1/tca/daily
GET  /api/v1/tca/trades/{trade_id}
GET  /api/v1/tca/summary

# 信号融合
GET  /api/v1/signals/fusion/{symbol}    — 单标的六维融合快照
GET  /api/v1/signals/conflict-alerts    — 当前存在信号冲突的持仓列表
```

---

*文档维护人：系统开发者 | 制定日期：2026-02-27 | 下次评审：V10.2-M3 完成后*
