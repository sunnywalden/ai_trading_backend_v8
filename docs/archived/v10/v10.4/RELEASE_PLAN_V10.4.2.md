# V10.4.2 版本规划 — 信号精英化：高置信度多维共振门控

> **AI量化交易闭环系统** — V10.4.2 版本规划  
> 文档版本：Draft v1.0 | 制定日期：2026-03-05  
> 基础版本：V10.4.1（待发布）  
> 定位：**"不出手则已，出手必有把握"——构建华尔街顶级私募级别的信号质量门控体系**

---

## 0. 产品经理视角诊断

### 0.1 核心问题：过度交易侵蚀 Alpha

> "Galton & Greenblatt 的研究反复证明：高频小额交易者的净 Sharpe 通常低于 0.3，而只做最高确定性机会的组合型基金 Sharpe 普遍超过 1.5。区别不在于信号多，而在于**敢不敢放弃低质信号**。"

| 当前状态 | 问题诊断 | 目标状态 |
|---------|---------|---------|
| 同时持仓 10+ 标的 | 组合过度分散，稀释高确定性头寸的 Alpha | ≤ 6 个并发持仓（可配置 `MAX_CONCURRENT_POSITIONS=6`）|
| 每日 30+ 信号输出 | 信号通货膨胀，置信度失真，滑点与摩擦成本侵蚀净值 | 每日有效推进信号 ≤ 5 个（可配置 `MAX_DAILY_SIGNALS=5`）|
| 置信度阈值 ~70 | 30% 置信区间过宽，接近"以为有优势实则是噪声" | 置信度 ≥ 95（可配置 `SIGNAL_CONFIDENCE_THRESHOLD=95`）|
| 单维度可触发信号 | 任何一个维度达标即可推进，无交叉验证 | 需 ≥ 4/6 维度共振（可配置 `SIGNAL_RESONANCE_MIN_DIMS=4`）|

**核心命题**：当前系统是"宽入窄出"——信号容易进入，执行偶有把关。V10.4.2 要实现"窄入高出"——信号很难通过质量门，但通过的信号有极高的期望收益。

---

### 0.2 华尔街顶级私募的信号纪律对标

| 机构风格 | 信号管控逻辑 | 借鉴点 |
|---------|------------|-------|
| Renaissance Medallion | 统计套利模型对信号 p-value 要求极严，噪声信号直接丢弃 | IC 阈值门控 + 统计显著性 |
| Bridgewater Pure Alpha | 每个头寸需通过"16个经济因子"全视角审查后才执行 | 多维强制共振机制 |
| Two Sigma | 机器学习模型输出置信区间，只在置信下界也高于阈值时才执行 | 保守置信下界校验 |
| Greenlight Capital（精选价值）| 组合同时持有标的 ≤ 10，每个都是高确信度 | 硬性最大仓位数量上限 |
| Citadel Wellington | 风险预算严格分配，每个信号必须通过独立的风险过滤层 | 独立风险预算层 |

---

### 0.3 当前信号管道的结构性漏洞

```
当前管道（问题版）：
  信号生成 ──┐
  技术面 ──┤ → composite_score ≥ 70 → 推进交易  ← ❌ 阈值太低
  基本面 ──┤                                      ← ❌ 无维度共振要求
  宏观 ────┤   ↑ max_daily_trades ≤ 10 门控       ← ❌ 数量限制宽松
  波动率 ──┤
  期权 ────┴──────────────────────────────────────────────────────

问题：30+ 信号通过了 composite_score ≥ 70，触发了 10 笔交易。
其中可能只有 3~5 个信号具有真实边际优势。
```

---

## 1. V10.4.2 版本目标与北极星

### 1.1 量化目标

| 目标 | 量化指标 | 当前基准 | V10.4.2 目标 |
|------|---------|---------|------------|
| 信号精英化率 | `conviction_score ≥ 95` 信号占总生成信号的比例 | ~5%（被动结果）| **≤ 15%**（主动筛选结果，低是正常的）|
| 日均推进信号 | 每个交易日推进至执行的信号数 | 30+ | **≤ 5**（默认配置）|
| 并发持仓上限 | 任意时刻的持仓标的数量 | 10+ | **≤ 6**（默认配置）|
| 置信度门槛 | composite_score 最低准入阈值 | 70 | **≥ 95**（默认配置）|
| 维度共振要求 | 同向维度最低数量 | 无 | **≥ 4/6 维度**（默认配置）|
| 反共振否决 | 任一关键维度强烈反向时的拒绝率 | 无机制 | **100% 触发否决**（硬规则）|
| 策略信号胜率（3个月滚动）| 已推进信号的实际胜率 | ~55%（估算）| **目标 ≥ 65%**（精英化副产物）|
| 年化 Sharpe 提升（预期）| 组合 Sharpe Ratio | ~0.6（估算）| **目标 ≥ 1.0**（6个月可验证）|

### 1.2 设计原则（不可妥协）

1. **精准优于数量**：宁可一天零信号，也不推进低质信号
2. **多维强制共振**：不允许任何单维度独自撑起一个交易决策
3. **保守置信校正**：使用置信度的校准下界，而非原始分
4. **硬性预算约束**：信号预算、仓位数量均为硬上限，不可被 AI 自行突破
5. **可解释的拒绝**：每个被拒的信号必须有可查的拒绝理由（审计链路）

---

## 2. 核心设计：五层信号漏斗（Signal Conviction Funnel）

```
原始信号池（所有 watchlist 标的）
        │  Layer 0: 宇宙过滤
        │  ─ 仅考虑 watchlist 内的标的（可配置）
        │  ─ 过滤停牌/流动性不足（ADV < MIN_ADV_THRESHOLD）
        ▼
通过 Layer 0 的候选信号
        │  Layer 1: 市场体制门控（Regime Gate）
        │  ─ CRISIS 体制：关闭所有做多信号，仅允许防御性减仓
        │  ─ HIGH_VOL：置信度阈值自动提升 +5（更严）
        │  ─ BEAR_TREND：仅允许 SHORT 或强防御品种做多
        ▼
通过 Layer 1 的候选信号
        │  Layer 2: 组合级预检（Portfolio Pre-check）
        │  ─ 当前并发持仓 ≥ MAX_CONCURRENT_POSITIONS → 拒绝所有新开仓
        │  ─ 当日已推进信号数 ≥ MAX_DAILY_SIGNALS → 拒绝（除非 force_override）
        │  ─ 新仓与现有持仓相关性 ≥ MAX_POSITION_CORRELATION(0.7) → 拒绝（防止集中风险）
        ▼
通过 Layer 2 的候选信号
        │  Layer 3: 多维共振验证（Resonance Gate）—— 核心创新
        │  ─ 计算 6 个维度中同向的数量 (aligned_count)
        │  ─ aligned_count < SIGNAL_RESONANCE_MIN_DIMS(4) → 拒绝
        │  ─ 任一关键维度（技术/基本面）方向强烈相反 → 直接否决（Anti-resonance Kill Switch）
        │  ─ 共振维度覆盖度：必须包含 technical + 至少 2 个其他维度（防止技术单指标堆砌）
        ▼
通过 Layer 3 的候选信号
        │  Layer 4: 置信度校准门（Conviction Score Gate）—— 核心创新
        │  ─ 计算 Conviction Score（综合校准分，见 §3.1）
        │  ─ conviction_score < SIGNAL_CONFIDENCE_THRESHOLD(95) → 拒绝
        │  ─ 夏普支撑验证：预期回报/风险 < MIN_EXPECTED_SHARPE(0.5) → 拒绝
        ▼
通过所有层的精英信号 ✅
        │  进入 AI 组合决策 → 执行
        ▼
执行后写入审计日志（含每层通过/拒绝原因）
```

**漏斗预期效果**（基于当前系统数据估算）：

| 层级 | 预期通过率 | 备注 |
|------|-----------|------|
| Layer 0: 宇宙过滤 | ~60% | 过滤低流动性 |
| Layer 1: 体制门控 | ~80% | 正常市场体制下大部分通过 |
| Layer 2: 组合预检 | ~40% | 持仓数量和每日配额硬约束 |
| Layer 3: 共振验证 | ~30% | 核心筛选，大幅淘汰单维信号 |
| Layer 4: 置信度校准 | ~40% | 在通过共振后的最终淘汰 |
| **总体通过率** | **~5~10%** | 30 个信号 → 约 2~4 个精英信号 |

---

## 3. 功能规划详述

### 3.1 Conviction Score（信号信念评分）

**新增核心指标**，替代简单的 `composite_score` 作为最终门控依据。

```python
conviction_score = (
    composite_score        * 0.40   # 现有六维加权分（0-100）
    + resonance_bonus      * 0.25   # 共振溢价（见下）
    + regime_alignment     * 0.15   # 当前体制与信号方向的匹配度（0-100）
    + historical_ic_bonus  * 0.10   # 该标的信号历史 IC（0-100）
    + timing_quality       * 0.10   # 信号时机质量：Alpha Decay 曲线位置（0-100）
)
```

**共振溢价（resonance_bonus）计算**：

```
aligned_count = 6维中同向维度数

resonance_bonus =
    aligned_count == 6 → 100（完美共振，极罕见）
    aligned_count == 5 → 90（强共振）
    aligned_count == 4 → 70（达标共振，最低）
    aligned_count == 3 → 30（弱共振，通常被 Layer 3 拒绝）
    aligned_count <= 2 → 0（无共振，直接否决）
```

**Anti-resonance Kill Switch（反共振一票否决）**：

```python
# 任意以下条件触发 → conviction_score 强制归零
kill_conditions = [
    tech_direction != 0 and fundamental_direction != 0 
        and tech_direction != fundamental_direction,  # 技术/基本面对立
    macro_regime == "CRISIS",                          # 危机体制
    macro_score < 30 and signal_direction == "LONG",  # 宏观极度悲观仍做多
    options_score < 20 and signal_direction == "LONG", # 期权市场强烈看空仍做多
]
```

**校准下界**：借鉴 Two Sigma 方法，使用历史校准数据计算置信区间下界（`calibrated_lower_bound`），并要求：

```python
# 不仅 conviction_score ≥ 95，还要求
calibrated_lower_bound ≥ SIGNAL_CONFIDENCE_FLOOR  # 默认 85
# 防止过拟合：模型可能对特定标的置信过高
```

---

### 3.2 新配置参数体系（`SignalQualityConfig`）

系统新增统一配置模型，所有信号质量参数可在运行时通过 API 或环境变量调整：

```python
class SignalQualityConfig(BaseSettings):
    # ── 置信度门控 ──────────────────────────────
    SIGNAL_CONFIDENCE_THRESHOLD: int = 95        # Conviction Score 最低门槛
    SIGNAL_CONFIDENCE_FLOOR: int = 85            # 校准下界最低要求
    MIN_EXPECTED_SHARPE: float = 0.5             # 预期夏普下限

    # ── 多维共振要求 ────────────────────────────
    SIGNAL_RESONANCE_MIN_DIMS: int = 4            # 最少同向维度数（6维中）
    RESONANCE_REQUIRED_DIMS: list[str] = ["technical"]  # 必须共振的维度
    ANTI_RESONANCE_KILL: bool = True             # 是否启用一票否决

    # ── 组合级约束 ──────────────────────────────
    MAX_CONCURRENT_POSITIONS: int = 6            # 最大并发持仓数
    MAX_DAILY_SIGNALS: int = 5                   # 每日最大推进信号数
    MAX_POSITION_CORRELATION: float = 0.70       # 新仓与现有持仓最大相关性

    # ── 体制自适应调节 ──────────────────────────
    HIGH_VOL_THRESHOLD_BUMP: int = 5             # HIGH_VOL 体制阈值自动提升幅度
    CRISIS_LONG_BLOCK: bool = True               # CRISIS 体制拒绝做多

    # ── 流动性过滤 ──────────────────────────────
    MIN_ADV_THRESHOLD: float = 1_000_000         # 最小日均成交量（美元）
    MIN_MARKET_CAP: float = 500_000_000          # 最小市值（美元）

    # ── 紧急覆盖（谨慎使用）──────────────────────
    QUALITY_GATE_BYPASS_ROLES: list[str] = ["SUPERADMIN"]  # 仅此角色可强制绕过
```

**配置热加载**：所有参数支持运行时通过 `PATCH /api/v1/system/signal-quality-config` 修改，无需重启服务。修改记录写入审计日志。

---

### 3.3 信号拒绝审计日志（Signal Quality Audit Log）

每个经过漏斗的信号（无论通过还是被拒）均记录完整的审计条目：

```json
{
  "audit_id": "uuid",
  "signal_id": "uuid",
  "symbol": "NVDA",
  "generated_at": "2026-03-05T09:31:00Z",
  "evaluated_at": "2026-03-05T09:31:01Z",
  "funnel_result": "REJECTED",
  "rejected_at_layer": 3,
  "rejection_reason": "INSUFFICIENT_RESONANCE",
  "rejection_detail": "aligned_count=3 < min_required=4; 宏观维度方向相反(score=35/direction=-1)",
  "conviction_score": null,
  "composite_score": 78.5,
  "resonance_details": {
    "aligned_count": 3,
    "aligned_dims": ["technical", "sentiment", "options"],
    "opposing_dims": ["macro"],
    "neutral_dims": ["fundamental", "volume_anomaly"]
  },
  "regime": "HIGH_VOL",
  "anti_resonance_triggered": false
}
```

**审计日志用途**：
- 前端"信号哨所（Signal Watchtower）"页面可视化漏斗拒绝分布
- 定期分析拒绝原因 → 优化漏斗参数
- 被拒信号的纸上跟踪（Ghost Trade）：计算"如果通过了会怎样" → 反事实校验门槛是否合理

---

### 3.4 纸上幽灵交易（Ghost Trade Tracker）

> 灵感来源：Bridgewater 的"影子组合"（Shadow Portfolio）——对所有被漏斗拒绝的信号进行无资金的虚拟跟踪，用于验证门槛是否过松或过严。

**工作机制**：
1. 被 Layer 3 或 Layer 4 拒绝的信号，自动创建 `ghost_trade` 记录（不执行，仅虚拟进入）
2. 按信号的 `entry_price`、`stop_loss`、`take_profit` 虚拟跟踪最多 `GHOST_TRADE_MAX_DAYS=10` 天
3. 每日收盘后自动更新 `ghost_pnl`
4. 统计"幽灵胜率"与"实际信号胜率"对比：
   - 幽灵胜率 >> 实际胜率 → 门槛过严，错过了好机会 → 考虑降低
   - 幽灵胜率 << 实际胜率 → 门槛合理，当前精选策略有效
5. 月度报告：`Ghost Trade Analysis` 纳入 AI 周报

---

### 3.5 信号预算可视化（Signal Budget Dashboard Widget）

前端新增"信号预算仪表盘"小组件，嵌入 Dashboard/War Room：

```
┌─────────────────────────────────────────────────┐
│  📡 今日信号预算                      2026-03-05 │
│                                                  │
│  已推进信号    ■■■□□   3 / 5         (60%)       │
│  生成候选      27 个候选 → 3 个精英通过 (11%)     │
│                                                  │
│  并发持仓      ■■■■□□   4 / 6        (67%)       │
│                                                  │
│  漏斗分布：                                      │
│  L0:宇宙  27 → L1:体制  22 → L2:组合  14        │
│  L3:共振  6  → L4:置信  3  → ✅推进  3          │
│                                                  │
│  [查看拒绝详情]  [调整参数]                       │
└─────────────────────────────────────────────────┘
```

---

### 3.6 体制自适应信号门控（Regime-Adaptive Gating）

在现有 Regime 体制基础上，细化信号准入规则：

| 体制 | 置信度门槛 | 共振要求 | 方向限制 | 最大仓位数 |
|------|-----------|---------|---------|-----------|
| BULL_TREND | 93（降低，市场顺风时）| ≥ 4/6 | LONG/SHORT 均可 | 6 |
| SIDEWAYS | 95（标准）| ≥ 4/6 | 优先做多强势板块 | 5 |
| BEAR_TREND | 97（提升）| ≥ 5/6 | 仅 SHORT 或防御 | 4 |
| HIGH_VOL | 97（提升）| ≥ 5/6 | LONG 须有对冲 | 3 |
| CRISIS | 99（极限）| ≥ 6/6 | 仅防御/平仓 | 2 |

---

### 3.7 Signal Watchtower（信号哨所页面）

前端新增轻量页面（替代原有散落的信号列表），专门用于信号质量监控：

**页面区域**：

1. **漏斗实时视图**：每个活跃信号在漏斗中的位置（动态流向图）
2. **被拒信号列表**：含拒绝理由、conviction_score 分布
3. **幽灵交易追踪**：被拒信号的虚拟 PnL 表现
4. **历史精英率趋势**：每日通过率折线图（目标：稳定在 5~15%）
5. **参数调优面板**：直接修改 `SignalQualityConfig` 的关键参数（带权限控制）

---

## 4. 技术实现要点

### 4.1 新增/修改服务

| 服务/模块 | 类型 | 变更说明 |
|---------|------|---------|
| `signal_conviction_scorer.py` | 🆕 新增 | 实现 Conviction Score 计算逻辑（§3.1）|
| `signal_quality_funnel.py` | 🆕 新增 | 五层漏斗主逻辑，依赖 conviction_scorer |
| `signal_quality_config.py` | 🆕 新增 | Pydantic 配置模型 + 热加载（§3.2）|
| `ghost_trade_service.py` | 🆕 新增 | 幽灵交易创建、追踪、统计（§3.4）|
| `signal_fusion_engine.py` | 🔧 修改 | 增加 anti_resonance_kill 输出字段 |
| `autonomous_decision_service.py` | 🔧 修改 | 决策前必须通过 SignalQualityFunnel |
| `signal_audit_log_service.py` | 🆕 新增 | 拒绝理由持久化（§3.3）|

### 4.2 数据库新增模型

```python
# 信号质量审计日志
class SignalQualityAuditLog(Base):
    __tablename__ = "signal_quality_audit_logs"
    id: UUID
    signal_id: UUID  # FK → trading_signals
    funnel_result: str                # PASSED / REJECTED
    rejected_at_layer: Optional[int] # 1~4
    rejection_reason: Optional[str]
    rejection_detail: Optional[str]
    conviction_score: Optional[float]
    composite_score: float
    aligned_count: int
    aligned_dims: list[str]
    opposing_dims: list[str]
    anti_resonance_triggered: bool
    regime: str
    created_at: datetime

# 幽灵交易
class GhostTrade(Base):
    __tablename__ = "ghost_trades"
    id: UUID
    signal_id: UUID
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    rejection_reason: str
    ghost_pnl: Optional[float]      # 虚拟盈亏（每日更新）
    ghost_result: Optional[str]     # WIN / LOSS / OPEN / EXPIRED
    tracking_start: datetime
    tracking_end: Optional[datetime]
    max_tracking_days: int = 10
    created_at: datetime
```

### 4.3 API 新增端点

```
GET  /api/v1/signals/quality-config            # 获取当前质量配置
PATCH /api/v1/signals/quality-config           # 热更新质量配置（需 SUPERADMIN）
GET  /api/v1/signals/audit-log                 # 获取信号审计日志（含拒绝理由）
GET  /api/v1/signals/funnel-stats              # 获取漏斗统计（各层通过率）
GET  /api/v1/signals/ghost-trades              # 获取幽灵交易列表
GET  /api/v1/signals/ghost-trades/analysis     # 幽灵交易分析（对比真实 vs 幽灵胜率）
```

### 4.4 前端变更

| 变更 | 类型 | 文件 |
|------|------|------|
| Signal Watchtower 页面 | 🆕 新增 | `src/views/SignalWatchtowerPage.vue` |
| 信号预算 Widget | 🆕 新增 | `src/components/SignalBudgetWidget.vue` |
| War Room 嵌入 Widget | 🔧 修改 | `src/views/WarRoomPage.vue` |
| Dashboard 嵌入 Widget | 🔧 修改 | `src/views/DashboardPage.vue` |
| API Service | 🆕 新增 | `src/api/signalQualityService.ts` |

---

## 5. 实施里程碑

### M1：漏斗核心（约 4 天）

- [ ] `SignalQualityConfig` Pydantic 模型 + 环境变量绑定
- [ ] `SignalConvictionScorer` 计算引擎（含 resonance_bonus/regime_alignment）
- [ ] `SignalQualityFunnel` 五层主逻辑
- [ ] `anti_resonance_kill_switch` 集成到 `SignalFusionEngine`
- [ ] 单元测试：覆盖各层拒绝场景（conviction < threshold / aligned_count < min / kill switch 触发）

### M2：决策系统接入（约 2 天）

- [ ] `AutonomousDecisionService` 决策前调用漏斗（`await funnel.evaluate(signal)`）
- [ ] 漏斗通过则推进，拒绝则写审计日志并返回拒绝原因
- [ ] `MAX_CONCURRENT_POSITIONS` 硬约束接入实时持仓查询
- [ ] `MAX_DAILY_SIGNALS` 计数器（Redis 或 DB）

### M3：审计与幽灵交易（约 2 天）

- [ ] `SignalQualityAuditLog` 模型 + Migration
- [ ] `GhostTrade` 模型 + Migration
- [ ] `GhostTradeService`：自动创建、每日价格更新、结算逻辑
- [ ] API：`/audit-log` / `/ghost-trades` / `/ghost-trades/analysis`

### M4：前端可视化（约 3 天）

- [ ] `SignalBudgetWidget`：预算环形图 + 漏斗桑基流向
- [ ] `SignalWatchtowerPage`：拒绝列表 + 幽灵追踪 + 参数面板
- [ ] War Room + Dashboard 嵌入 Widget
- [ ] 配置热更新 UI（参数滑块 + 确认弹窗）

### M5：集成测试 & 参数校准（约 2 天）

- [ ] 使用历史信号数据回放漏斗（3个月历史数据）
- [ ] 验证漏斗总通过率落在 5~15% 目标区间
- [ ] 调整默认参数（`SIGNAL_CONFIDENCE_THRESHOLD`/`SIGNAL_RESONANCE_MIN_DIMS`）
- [ ] Paper Trading 验证：新门控下的信号质量是否提升

---

## 6. 风险与对冲

| 风险 | 概率 | 影响 | 对冲方案 |
|------|------|------|---------|
| 门槛过严 → 信号枯竭，系统空转 | 中 | 高 | Ghost Trade Tracker 验证：幽灵胜率 >> 实际则降低门槛 |
| Conviction Score 权重设计偏差 | 中 | 中 | 首发后 2 周 A/B 观察期，参数可热更新 |
| 体制检测延迟导致不当放行 | 低 | 中 | Layer 1 体制判断使用最近 15 分钟数据，延迟影响有限 |
| 并发持仓数降低导致分散化不足 | 低 | 低 | Portfolio 检查同时跟踪行业集中度，防止单行业超配 |
| 历史 IC 数据不足（V10.4 数据治理未完成）| 高 | 低 | `historical_ic_bonus` 组件在 IC 不可用时退化为 0（从分值权重剔除并重新归一化）|

---

## 7. 成功标准（2 周后可验证）

### 定量指标

| 指标 | 验收标准 |
|------|---------|
| 日均推进信号数 | ≤ 5 个（正常市场体制下）|
| 同时持仓数 | ≤ 6 个 |
| 精英信号率 | 5~15%（拒绝了 85~95% 的候选信号）|
| 漏斗审计完整性 | 每个被拒信号 100% 有拒绝理由记录 |
| Ghost Trade 追踪覆盖率 | Layer 3+ 被拒信号 100% 创建幽灵交易 |
| 配置热更新响应 | < 5s（无重启）|

### 质性指标（4~8 周可观察）

- 交易决策"质感"提升：每个推进的信号背后都有清晰的多维支撑，AI reasoning 更有说服力
- 持仓结构更干净：少量高确信度头寸，而非多量低确信度头寸
- 周报幽灵分析成为优化漏斗的反馈机制，系统开始自我校准门槛

---

## 8. 与 V10.4 总体规划的关系

V10.4.2 是 V10.4 规划中 **M1（数据闭环治理）** 的高质量信号数据先决条件，同时也是 **独立可交付的精英化升级**，与 M2（UI 清洗）、M3（Copilot 全局化）正交，可并行推进。

```
V10.4 路线图更新：
  M1: 数据闭环治理         →  V10.4.0 / V10.4.1
  M2: UI 大清洗           →  V10.4.1 / V10.4.3
  M3: Copilot 全局化      →  V10.4.3
  M4: 自主循环稳定增强     →  V10.4.1 / V10.4.3
  M5: 移动触达            →  V10.4.4
  M6: 文档重构            →  持续进行
  
  ★ V10.4.2: 信号精英化     →  即本文档（独立里程碑）
```

---

*文档版本：Draft v1.0*  
*制定：产品经理（AI Quant PM 视角）*  
*最后更新：2026-03-05*
