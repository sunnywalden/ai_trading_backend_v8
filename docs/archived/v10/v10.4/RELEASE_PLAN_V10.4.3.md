# V10.4.3 版本规划 — 减仓·平仓优先通道：消除系统性阻断风险

> **AI量化交易闭环系统** — V10.4.3 版本规划  
> 文档版本：Draft v1.0 | 制定日期：2026-03-06  
> 基础版本：V10.4.2（已完成信号精英化五层漏斗）  
> **核心命题**：*"风控系统的最大悖论：当市场最危险的时候，系统反而最容易拒绝减仓指令。"*

---

## 0. 产品经理视角：这是一个 P0 安全缺陷

### 0.1 问题本质

V10.4.2 引入了严格的"五层信号漏斗 + RiskGate"体系，极大提升了**开仓信号**的质量。  
但这套体系存在一个**结构性漏洞**：它对减仓/平仓信号 **完全适用相同的限制**，导致：

> **当你最需要出场的时候，系统最有可能阻止你出场。**

| 场景 | 触发条件 | 系统当前行为 | 实际风险 |
|------|---------|------------|---------|
| 市场暴跌，需要止损 | 单日亏损 ≥ `MAX_DAILY_LOSS_PCT` (3%) | Circuit Breaker 触发 → **连平仓也被拒绝** | 损失无法止住，越跌越烂 |
| 当日已开 10 仓，预警信号出现 | `daily_trades = MAX_DAILY_TRADES` | 日交易笔数超限 → **无法提交减仓指令** | 仓位持续暴露在风险中 |
| 快速开仓后立刻反转 | 开仓后 < 120 分钟 | 冷却锁 → **止损信号被丢弃** | 无法快速退出错误交易 |
| RebalanceMonitor 触发减仓 | AI 评分 REDUCE/SELL | 质量漏斗 Layer 2~4 → **被当成开仓信号拦截** | 风险累积不能及时疏解 |
| 止损系统触发 EXIT 信号 | PositionMonitor 止损触发 | 经过完整五层漏斗 → **可能因置信度不足被拒** | 止损系统形同虚设 |

### 0.2 架构根源分析

当前系统在设计时将"信号"作为统一对象流转于各风控层，**没有区分信号意图**：

```
当前（错误）：
  任意信号（开仓/减仓/平仓/止损）
    → SignalQualityFunnel（五层）
    → RiskGate（VaR/熔断/日笔数/仓位占比）
    → CooldownGuard（120分钟）
    → RedisOrderLock（180秒）
    → OrderExecutor（数量计算）

应有（正确）：
  开仓/加仓信号    → 完整质量漏斗 + 完整 RiskGate（维持现状）
  减仓/平仓/止损   → 快速通道 + 轻量合规检查（本版新增）
```

**一句话原则**：减仓/平仓是**降低风险**的操作，不应受到**为了控制新增风险而设计**的同等限制。

---

## 1. 漏洞盘点（全系统扫描结果）

### 1.1 RiskGate 的三处错误拦截

**文件**：`app/services/risk_gate_service.py`

```python
# 问题 1：Circuit Breaker 拦截平仓
# 当日亏损触发熔断时，连平仓指令也会被拒绝
if daily_loss_pct >= settings.MAX_DAILY_LOSS_PCT:
    return RiskGateResult(passed=False, ...)   # ❌ 不分指令类型，一刀切

# 问题 2：MAX_DAILY_TRADES 计数减仓/平仓
if daily_trades_today >= settings.MAX_DAILY_TRADES:
    return RiskGateResult(passed=False, ...)   # ❌ 开仓次数耗尽后连止损都无法触发

# 问题 3：VaR/压力测试检查对 SELL 无意义
# SELL 操作本身就是在降低 VaR，不应被 VaR 超限阻止
var_pct = self._estimate_var(current_positions, current_equity)
if var_pct > effective_var_limit:
    return RiskGateResult(passed=False, ...)   # ❌ SELL 应豁免此项
```

### 1.2 SignalQualityFunnel 的全程拦截

**文件**：`app/services/signal_quality_funnel.py`

```python
# 问题 4：Layer 2 日配额把减仓信号也占用
# MAX_DAILY_SIGNALS=5 时，5 个开仓信号通过后，当天的减仓信号无法再通过
if daily_signals_executed >= cfg.MAX_DAILY_SIGNALS:   # ❌ 减仓/平仓不应占用配额

# 问题 5：Layer 3 多维共振要求对减仓无意义
# 止损/减仓不需要 4/6 维度共振，它的触发条件是持仓风险而非多维度机会
# 当前代码: 所有信号走相同的漏斗，无法区分信号意图

# 问题 6：Layer 4 置信度阈值=95 时，止损信号可能置信度≈50 而被拒
# 正在下跌途中的 EXIT 信号，composite_score 往往较低（空头共振，但无技术突破）
```

### 1.3 AutonomousEngine 的冷却/并发保护

**文件**：`app/services/autonomous_engine.py`

```python
# 问题 7：120分钟冷却锁对减仓/平仓同样生效
# 开仓后立刻下跌，2小时内无法自动止损
cooldown_min = int(getattr(settings, "AUTONOMOUS_ORDER_COOLDOWN_MINUTES", 120) or 120)
if await self._has_recent_autonomous_execution(...direction=SELL...):
    # 即使是 SELL，也被冷却保护阻止          # ❌

# 问题 8：Redis 180s 并发锁对退出重试造成阻碍
# 平仓下单失败后重试时，被同一把锁阻止 180 秒
lock_seconds = int(getattr(settings, "AUTONOMOUS_ORDER_LOCK_SECONDS", 180) or 180)
```

### 1.4 SignalPositionFilter 拒绝而非调整

**文件**：`app/engine/signal_position_filter.py`

```python
# 问题 9：减仓数量 > 持仓时直接拒绝，本应调整为全仓平
def _filter_reduce_signal(self, signal, current_position):
    if abs(current_position.qty) < signal.suggested_quantity:
        return FilterResult(
            passed=False,
            reason=f"减仓数量超过持仓（可转为平仓）"   # ❌ 只说"可以"但没有做
        )
```

### 1.5 OrderExecutor 数量计算错误

**文件**：`app/engine/order_executor.py`

```python
# 问题 10：EXIT 信号的数量用账户权益百分比计算，而不是实际持仓数量
# 导致"平仓"只平了一部分，或者数量与实际持仓不匹配
position_size_pct = signal.suggested_quantity or 0.10   # ❌ EXIT 信号应直接取持仓数量
quantity = int(account_equity * position_size_pct / current_price)
```

### 1.6 SafetyGuard 名义金额对减仓的误阻

**文件**：`app/services/safety_guard.py`

```python
# 问题 11：大仓位减仓时可能超过 max_order_notional_usd
async def check_order(self, side: str, notional_usd: float, ...) -> SafetyCheckResult:
    if notional_usd > self.limits.max_order_notional_usd:
        return SafetyCheckResult(False, ...)   # ❌ SELL 应豁免此项
```

---

## 2. V10.4.3 解决方案设计

### 2.1 架构总图

```
V10.4.3 执行管道（双轨制）：

Signal 入口
    │
    ├── [intent = REDUCE / EXIT / STOP_LOSS_EXIT]
    │       │
    │       ▼  ReduceExitFastPath（新增）
    │       ├─ 持仓确认（有持仓才能平）
    │       ├─ 市场时段确认（市场开放才执行）
    │       ├─ 账户合规确认（账户有效、未被冻结）
    │       └─ 数量自动对齐（按实际持仓计算）
    │               │
    │               ▼ 绕过 Quality Funnel 直通 Broker
    │
    └── [intent = ENTRY / ADD]
            │
            ▼  SignalQualityFunnel（五层，V10.4.2）
            → RiskGate（完整检查）
            → CooldownGuard（120分钟）
            → RedisOrderLock（180秒）
            → OrderExecutor（按比例计算数量）
```

### 2.2 P0：RiskGate 减仓/平仓豁免（核心修改）

**修改文件**：`app/services/risk_gate_service.py`

```python
async def check(
    self,
    account_id: str,
    symbol: str,
    qty: float,
    side: str,
    current_equity: float,
    current_positions: dict,
    daily_trades_today: int = 0,
    daily_realized_pnl: float = 0.0,
    signal_intent: str = "OPEN",      # 新增参数：OPEN / REDUCE / EXIT
) -> RiskGateResult:

    is_closing = signal_intent in ("REDUCE", "EXIT", "STOP_LOSS_EXIT")

    # ── 1. 熔断检查（降级处理：EXIT 允许执行，仅阻止新开仓）──
    daily_loss_pct = abs(daily_realized_pnl) / current_equity if daily_realized_pnl < 0 else 0
    if daily_loss_pct >= settings.MAX_DAILY_LOSS_PCT:
        if is_closing:
            # ✅ 平仓/减仓：熔断器不拦截，记录告警但允许通过
            logger.warning(
                f"[RiskGate] Circuit breaker ACTIVE but allowing CLOSE/REDUCE for {symbol} "
                f"(daily_loss={daily_loss_pct:.1%})"
            )
            # 直接返回通过，跳过后续检查
            return RiskGateResult(
                passed=True,
                reason="circuit-breaker-active-but-closing-allowed",
                circuit_breaker=True,   # 标记熔断器激活，供审计日志用
                details={"daily_loss_pct": daily_loss_pct, "bypass_reason": "closing_intent"},
            )
        else:
            return RiskGateResult(passed=False, circuit_breaker=True, ...)

    # ── 2. 日交易笔数限制（仅对开仓计数）──
    if not is_closing:   # ✅ 减仓/平仓不占用日交易笔数
        if daily_trades_today >= settings.MAX_DAILY_TRADES:
            return RiskGateResult(passed=False, ...)

    # ── 3. 单标的仓位占比（仅 BUY 检查）── 无变化

    # ── 4. VaR 检查（仅 OPEN 类信号）──
    if not is_closing:   # ✅ REDUCE/EXIT 本身降低 VaR，豁免 VaR 检查
        var_pct = self._estimate_var(current_positions, current_equity)
        if var_pct > effective_var_limit:
            return RiskGateResult(passed=False, ...)

    # ── 5. 压力测试（仅 OPEN 类信号）──
    if not is_closing:   # ✅ 同上
        stress_loss_pct = self._estimate_stress_loss(current_positions, current_equity)
        if stress_loss_pct > settings.MAX_STRESS_LOSS_PCT:
            return RiskGateResult(passed=False, ...)

    return RiskGateResult(passed=True, ...)
```

> **审计合规说明**：Circuit Breaker 激活期间执行的平仓操作需在审计日志中标注 `bypass_reason=closing_intent`，供事后复查。

### 2.3 P0：AutonomousEngine 信号意图路由

**修改文件**：`app/services/autonomous_engine.py`

**新增常量**：
```python
# 减仓/平仓意图集合（这些信号走快速通道）
CLOSING_SIGNAL_TYPES = frozenset(["EXIT", "REDUCE", "STOP_LOSS_EXIT"])
CLOSING_ACTIONS      = frozenset(["SELL", "REDUCE"])

def _is_closing_intent(signal: dict, decision: dict) -> bool:
    """判断信号是否为减仓/平仓意图"""
    signal_type = str(signal.get("signal_type") or "").upper()
    action      = str(decision.get("action") or "").upper()
    return signal_type in CLOSING_SIGNAL_TYPES or action in CLOSING_ACTIONS
```

**修改 run_decision_cycle**：

```python
is_closing = _is_closing_intent(signal, decision)

# ① Quality Funnel：减仓/平仓完全跳过
if not is_closing:
    _funnel_decision = await signal_quality_funnel.evaluate(...)
    if not _funnel_decision.passed:
        # reject ...
        continue
else:
    logger.info(
        f"[AutonomousEngine] Closing signal {signal['id']} ({signal.get('signal_type')}) "
        f"bypassing quality funnel → fast-path"
    )

# ② RiskGate：传入 signal_intent
gate = await risk_gate_service.check(
    ...
    signal_intent="EXIT" if is_closing else "OPEN",
)

# ③ 冷却保护：减仓/平仓豁免（或极短冷却 EXIT_COOLDOWN_MINUTES=5）
if not is_closing:
    if await self._has_recent_autonomous_execution(...):
        continue   # 只对 OPEN 类信号冷却
else:
    exit_cooldown = int(getattr(settings, "EXIT_ORDER_COOLDOWN_MINUTES", 5) or 5)
    if await self._has_recent_autonomous_execution(
        ..., cooldown_minutes=exit_cooldown
    ):
        # 极短冷却（防止完全重复提交，但不阻止止损重试）
        continue

# ④ Redis 并发锁：减仓/平仓缩短至 EXIT_LOCK_SECONDS=30
if is_closing:
    lock_seconds = int(getattr(settings, "EXIT_ORDER_LOCK_SECONDS", 30) or 30)
else:
    lock_seconds = int(getattr(settings, "AUTONOMOUS_ORDER_LOCK_SECONDS", 180) or 180)
```

### 2.4 P0：SignalQualityFunnel 配额不计减仓/平仓

**修改文件**：`app/services/signal_quality_funnel.py`

`evaluate()` 新增 `signal_type` 参数：

```python
async def evaluate(
    self,
    signal: SignalFunnelInput,
    db: AsyncSession,
    current_positions_count: int = 0,
    daily_signals_executed: int = 0,
    signal_type: str = "ENTRY",    # 新增：ENTRY / ADD / REDUCE / EXIT
) -> FunnelDecision:

    is_closing = signal_type in ("REDUCE", "EXIT", "STOP_LOSS_EXIT")

    # Layer 2: 组合预检 — 减仓/平仓不占用日配额
    def _layer2_portfolio(...):
        ...
        if not is_closing:
            if daily_signals_executed >= regime_cfg.get("MAX_DAILY_SIGNALS", cfg.MAX_DAILY_SIGNALS):
                return ("daily-quota-exhausted", f"今日信号配额已满 ...")
```

### 2.5 P1：SignalPositionFilter 数量自动对齐

**修改文件**：`app/engine/signal_position_filter.py`

```python
def _filter_reduce_signal(self, signal, current_position) -> FilterResult:
    if not current_position or abs(current_position.qty) < 0.01:
        return FilterResult(passed=False, reason="无持仓，无法减仓")

    if abs(current_position.qty) < signal.suggested_quantity:
        # ✅ 修复：自动调整为全部平仓，而不是拒绝
        logger.warning(
            f"[SignalPositionFilter] {signal.symbol}: reduce qty "
            f"{signal.suggested_quantity:.0f} > position {abs(current_position.qty):.0f}, "
            f"auto-adjusting to full close"
        )
        signal.suggested_quantity = abs(current_position.qty)
        signal.signal_type = SignalType.EXIT   # 升级为平仓信号
        if not signal.extra_metadata:
            signal.extra_metadata = {}
        signal.extra_metadata["auto_adjusted_to_exit"] = True
        signal.extra_metadata["original_reduce_qty"]   = signal.suggested_quantity

    return FilterResult(passed=True)
```

### 2.6 P1：OrderExecutor 修复 EXIT 数量计算

**修改文件**：`app/engine/order_executor.py`

```python
async def _calculate_order_params(self, signal, account_equity):
    ...
    # ✅ 修复：EXIT 信号直接使用持仓数量
    if signal.signal_type in (SignalType.EXIT,) or str(signal.direction).upper() == "SELL":
        current_pos_qty = (
            (signal.extra_metadata or {}).get("current_position", {}).get("qty")
            if signal.extra_metadata else None
        )
        if current_pos_qty is not None and abs(float(current_pos_qty)) > 0:
            quantity = int(abs(float(current_pos_qty)))
            logger.info(
                f"[OrderExecutor] EXIT signal: using actual position qty={quantity} "
                f"for {signal.symbol}"
            )
        # 若 extra_metadata 未含持仓，Fallback 到按比例（不回归到 10% 默认）
        elif signal.suggested_quantity and signal.suggested_quantity >= 1.0:
            quantity = int(signal.suggested_quantity)
    ...
```

### 2.7 P1：PositionMonitor 止损信号标记强制出场

**修改文件**：`app/engine/position_monitor.py`

```python
# 写入 EXIT 信号时，标记 force_exit=True（止损触发）
await self._write_exit_signal(
    session=self.session,
    account_id=account_id,
    symbol=symbol,
    qty=qty,
    reason=exit_reason,
    priority=priority,
    extra_metadata={
        "force_exit":   True,       # ✅ 新增：标记强制出场，不经漏斗
        "exit_reason":  exit_reason,
        "pnl_pct":      unrealized_pnl_pct,
        "trigger_price": current_price,
    },
)
```

**修改 AutonomousEngine** 处理 force_exit 信号：

```python
is_force_exit = bool((signal.get("extra_metadata") or {}).get("force_exit"))

if is_force_exit:
    # 强制出场：完全跳过漏斗 + 豁免冷却 + 优先执行
    logger.warning(
        f"[AutonomousEngine] FORCE EXIT signal for {signal.get('symbol')}: "
        f"bypassing ALL guards (stop-loss/take-profit triggered)"
    )
    is_closing = True
    # 不做漏斗检查、不做冷却检查、不做并发锁
    gate = await risk_gate_service.check(..., signal_intent="EXIT")
    # 直接执行，不放入普通队列
```

### 2.8 P1：SafetyGuard 减仓豁免名义金额检查

**修改文件**：`app/services/safety_guard.py`

```python
async def check_order(
    self,
    side: str,
    notional_usd: float,
    est_daily_pnl_pct=None,
    signal_intent: str = "OPEN",    # ✅ 新增参数
) -> SafetyCheckResult:
    is_closing = signal_intent in ("REDUCE", "EXIT")
    if not is_closing and notional_usd > self.limits.max_order_notional_usd:
        return SafetyCheckResult(False, f"订单名义金额超限 ...")
    return SafetyCheckResult(True)
```

### 2.9 P2：新增配置项到 settings

**修改文件**：`app/core/config.py`

```python
# V10.4.3: 减仓/平仓专属配置
EXIT_ORDER_COOLDOWN_MINUTES: int = 5      # 平仓/减仓方向冷却（分钟）
EXIT_ORDER_LOCK_SECONDS: int = 30         # 平仓/减仓 Redis 并发锁（秒）
ALLOW_CLOSING_DURING_CIRCUIT_BREAKER: bool = True  # 熔断期间允许平仓
```

**对应 `.env.example` 追加**：
```
EXIT_ORDER_COOLDOWN_MINUTES=5
EXIT_ORDER_LOCK_SECONDS=30
ALLOW_CLOSING_DURING_CIRCUIT_BREAKER=true
```

---

## 3. 变更范围总览

| 优先级 | 文件 | 变更类型 | 核心改动 |
|-------|------|---------|---------|
| **P0** | `risk_gate_service.py` | 逻辑修改 | 增加 `signal_intent` 参数；EXIT/REDUCE 豁免熔断、日笔数、VaR、压力测试 |
| **P0** | `autonomous_engine.py` | 路由修改 | 增加 `_is_closing_intent()` 判断；EXIT/REDUCE 绕过漏斗；差异化冷却/锁时间 |
| **P0** | `signal_quality_funnel.py` | 配额修改 | `evaluate()` 增加 `signal_type`；EXIT/REDUCE 不占 `MAX_DAILY_SIGNALS` 配额 |
| **P1** | `signal_position_filter.py` | 逻辑修改 | 减仓数量超持仓时自动调整为全平，不拒绝 |
| **P1** | `order_executor.py` | 数量计算修复 | EXIT 信号优先使用 `extra_metadata.current_position.qty` |
| **P1** | `position_monitor.py` | 元数据标记 | 止损/止盈触发的 EXIT 信号写入 `force_exit=True` |
| **P1** | `autonomous_engine.py` | 强制路径 | 识别 `force_exit=True` 信号，跳过所有防护直接执行 |
| **P1** | `safety_guard.py` | 豁免修改 | `check_order()` 增加 `signal_intent`；EXIT/REDUCE 豁免名义金额上限 |
| **P2** | `config.py` + `.env.example` | 配置新增 | `EXIT_ORDER_COOLDOWN_MINUTES=5` / `EXIT_ORDER_LOCK_SECONDS=30` |

**不需要 DB migration**（本版本全部为逻辑层修改，无新表）。

---

## 4. 执行风险与防护措施

### 4.1 "恶意绕过"风险

**风险**：有人故意将信号标记为 EXIT 以绕过风控。

**防护**：
- RiskGate 仍检查`持仓确认`：EXIT 类信号若账户中无对应持仓，拒绝执行（`signal_position_filter` 已有此检查）
- 所有 EXIT 信号的 `signal_intent` 豁免均写入 `autonomous_execution_intent.reason` 审计字段
- 熔断期间平仓的 `circuit_breaker=True` 标记保留，供事后合规复查

### 4.2 止损信号"竞争执行"风险

**风险**：同一持仓同时触发多个 EXIT 信号（PositionMonitor + RebalanceMonitor + AI 决策）。

**防护**：
- `signal_position_filter._filter_exit_signal()` 已有"无持仓不通过"检查，首个 EXIT 执行成功后持仓清零，后续 EXIT 自然被拒
- `idempotency_key` 在 `autonomous_execution_intent` 层防止重复完全相同的执行意图
- 第一个 EXIT 成功后，`PositionMonitor` 下次扫描将不再有持仓，不生成新 EXIT

### 4.3 熔断期平仓的合规标注

**要求**：监管环境中，熔断期间的任何交易须有合理理由。

**实现**：
```python
# autonomous_execution_intent 的 reason 字段记录
reason = "circuit-breaker-active-exit-allowed(closing_intent)"
# audit_log 的 regime_at_decision / circuit_breaker_active 字段同步标注
```

---

## 5. 量化目标与验收标准

| 验收指标 | 当前状态 | V10.4.3 目标 | 验证方法 |
|---------|---------|------------|---------|
| 熔断期间平仓成功率 | ~0%（被熔断器拒绝）| **≥ 95%（允许平仓）** | 模拟熔断期触发 EXIT 信号，监控 intent status |
| 日笔数耗尽后的 EXIT 成功率 | ~0% | **≥ 95%** | `MAX_DAILY_TRADES=1` 时发出 EXIT 信号，监控执行情况 |
| 止损触发到订单提交延迟 | 可能 > 120 分钟（冷却） | **≤ 30 秒** | PositionMonitor force_exit 信号时序追踪 |
| EXIT 信号被 quality funnel 拦截率 | 可能 > 80%（高 VIX 时置信度低） | **0%（完全跳过漏斗）** | 审计日志中 EXIT 信号的 funnel_layer 字段 |
| 减仓数量误差（vs 实际持仓）| 可能偏差 30-50%（用权益比例计算）| **≤ 1 股误差** | 对比 executed_quantity vs actual_position_qty |
| 减仓超仓时被拒率 | 100%（超持仓减仓直接拒绝）| **0%（自动调整为全平）** | 发送 qty > actual_pos 的 REDUCE 信号 |

---

## 6. 实现优先级与排期

### Sprint 1（P0，48h）

- [ ] `risk_gate_service.py`：增加 `signal_intent` 参数 + EXIT 三项豁免
- [ ] `autonomous_engine.py`：增加 `_is_closing_intent()` + 路由逻辑
- [ ] `signal_quality_funnel.py`：`MAX_DAILY_SIGNALS` 配额豁免 EXIT/REDUCE
- [ ] `config.py` + `.env.example`：新增三项配置

### Sprint 2（P1，72h）

- [ ] `signal_position_filter.py`：减仓数量自动对齐
- [ ] `order_executor.py`：EXIT 数量从 `extra_metadata.current_position.qty` 取值
- [ ] `position_monitor.py`：止损/止盈写入 `force_exit=True`
- [ ] `autonomous_engine.py`：识别 `force_exit=True` → 强制路径
- [ ] `safety_guard.py`：`signal_intent` 增加，EXIT/REDUCE 豁免名义上限

### Sprint 3（P2，24h）

- [ ] 端到端集成测试（模拟：熔断期 EXIT / 日笔数耗尽 REDUCE / 止损触发 force_exit）
- [ ] 审计日志 UI：在 AutonomyPage 执行意图列表中标注 `[快速通道]` / `[强制出场]`
- [ ] 告警：熔断期间有 EXIT 执行时，向 Notification Service 发一条 INFO 级别通知

---

## 7. 测试用例设计

### TC-01：熔断期间平仓成功

```python
async def test_circuit_breaker_allows_exit():
    # Setup: daily_loss_pct > MAX_DAILY_LOSS_PCT
    result = await risk_gate_service.check(
        ..., daily_realized_pnl=-5000, current_equity=100000,
        signal_intent="EXIT"
    )
    assert result.passed == True
    assert result.circuit_breaker == True   # 标记但通过
    assert "closing_intent" in (result.details.get("bypass_reason") or "")
```

### TC-02：日笔数耗尽后 REDUCE 通过

```python
async def test_daily_trade_limit_not_block_reduce():
    result = await risk_gate_service.check(
        ..., daily_trades_today=10,  # MAX_DAILY_TRADES = 10
        signal_intent="REDUCE"
    )
    assert result.passed == True
```

### TC-03：减仓数量超持仓自动调整

```python
def test_reduce_qty_auto_adjust():
    signal.signal_type = SignalType.REDUCE
    signal.suggested_quantity = 200  # 持仓只有 100
    position = Position(symbol="TSLA", qty=100, ...)
    result = filter._filter_reduce_signal(signal, position)
    assert result.passed == True
    assert signal.suggested_quantity == 100          # 自动调整
    assert signal.signal_type == SignalType.EXIT     # 升级为平仓
    assert signal.extra_metadata["auto_adjusted_to_exit"] == True
```

### TC-04：force_exit 信号绕过所有保护

```python
async def test_force_exit_bypasses_all_guards():
    signal = {"signal_type": "EXIT", "extra_metadata": {"force_exit": True}}
    # 即使冷却中、熔断触发、VaR 超限，force_exit 也应成功提交
    result = await engine.run_decision_cycle(account_id, db)
    assert any(r["reason"] == "force-exit-bypass" for r in result)
```

---

## 8. 后续演进方向（V10.4.4+ 的候选特性）

1. **智能分批平仓**：大仓位平仓时自动分批（TWAP/VWAP），避免过大市场冲击
2. **对冲式止损**：止损触发时，先买入对应 Put 做保护，再逐步平仓（避免急速抛售）
3. **平仓时机优化**：EXIT 信号触发后，短期 TWAP 优化（5分钟内分批，提高成交价格）
4. **"减仓失败后的备用路径"**：若自动减仓失败（如市场暂停），自动升级告警级别为紧急，同时尝试对冲

---

*文档维护人：Architecture Team | 下一步：提交 Sprint 1 PR，关联 GitHub Issue #v10.4.3*
