# V10.1 版本规划

> **AI量化交易闭环系统** — V10.1 版本规划  
> 文档版本：Draft v1.0 | 制定日期：2026-02-26  
> 基础版本：V10.0（2026-02-24 发布）  
> 定位：**兑现承诺 + 打磨质量 + 扩展边界**

---

## 0. 规划背景

### 0.1 V10.0 交付总结

V10.0 实现了"AI 自主闭环"的整体架构，核心成就：

| 模块 | V10.0 状态 |
|------|-----------|
| AI 自主决策引擎（三级自主模式） | ✅ 框架完整，逻辑可运行 |
| DataHub 多数据源路由 | ✅ 完整 |
| 回测引擎（事件驱动 + Walk-Forward） | ✅ 完整 |
| 投资组合优化（Markowitz + Kelly） | ✅ 完整 |
| 风险门禁（VaR + 压力测试） | ✅ 完整 |
| TWAP/VWAP 执行算法 | ✅ 逻辑完整，内存运行 |
| Trading Copilot 对话接口 | ✅ 对话完整，指令执行未落地 |
| Paper Trading 账户隔离 | ✅ 完整 |
| 期权分析中心（只读） | ✅ 完整 |
| AI 周报服务 | ✅ 生成逻辑完整 |
| Tiger 真实下单 | ❌ `NotImplementedError` |
| Telegram 通知集成 | ❌ TODO 占位 |
| Dashboard 关键指标计算 | ⚠️ 多处 TODO 占位 |
| Copilot 操作指令执行 | ⚠️ 仅解析，未调用 |

### 0.2 核心矛盾

> "V10.0 完成了功能骨架，但个人量化交易系统最核心的'执行闭环'仍未完全打通——AI 可以决策，但真实下单路径断裂；通知机制缺失导致 SEMI 模式失去价值；Dashboard 指标计算是占位符意味着核心仪表盘不真实。"

### 0.3 V10.1 定位

```
V10.1 = 兑现 V10.0 承诺 × 打磨核心体验 × 扩展标的边界

优先级排序：
  P0 — 执行闭环完整性（Tiger 真实下单，覆盖美股/港股/期权）
  P1 — 仪表盘数据真实性（消除所有 TODO 占位）
  P2 — AI 决策质量提升（组合级决策 + 结构化输出）
  P3 — 扩展边界（ETF 支持 + 港股标的接入，数据源统一走 Tiger API）
  P4 — 可观测性与稳定性（集成测试 + WebSocket）

行情数据获取原则：
  美股股票 / 港股股票 / 期权 → 统一优先 Tiger API → yfinance 降级（仅美股）
  不引入 Futu API，避免多客户端维护复杂度
```

---

## 1. P0 — 执行闭环完整性

> **目标**：让 SEMI/FULL 模式真正可用于实盘

### 1.1 Tiger 真实下单接入

**问题**：`TigerOrderExecutor.submit_order()` 抛出 `NotImplementedError`，所有实盘交易退化为 Paper 模式。

**改造范围**：`app/services/order_service.py` → `TigerOrderExecutor`

**实现要点**：

```python
class TigerOrderExecutor:
    """Tiger OpenAPI 真实下单执行器"""

    async def submit_order(self, order: dict) -> dict:
        # 1. 根据 order_type 构建 TradeOrder 对象
        # 2. 调用 app/broker/factory.py 的券商客户端
        # 3. 统一映射 Tiger 返回字段 → OrderView
        # 4. 写入 trade_pnl_attribution 表追踪
        ...

    async def cancel_order(self, order_id: str) -> bool:
        # 调用 Tiger cancel_order API
        ...

    async def get_order_status(self, order_id: str) -> dict:
        # 轮询 Tiger order status
        ...
```

**验收标准**：
- [ ] `DRY_RUN=false` 时，`POST /api/v1/ai-advisor/execute` 可真实下单至 Tiger
- [ ] 订单状态（PENDING → FILLED/CANCELLED）异步同步回数据库
- [ ] `TradeMode=PAPER` 时自动回退到 `PaperOrderExecutor`，不变更原有逻辑

---

### 1.2 SEMI/FULL 模式 Telegram 通知落地

**问题**：`autonomous_engine.py` L248/L254 的两处 Telegram 通知是 `# TODO` 注释，SEMI 模式的"执行后推通知 + 撤销链接"功能实际无效。

**涉及代码**：
- `app/services/autonomous_engine.py` → `_notify_circuit_breaker()` / `_notify_suggestion()`
- `app/services/notification_service.py`（已有结构，需对接 Telegram Bot）

**实现要点**：

```python
# autonomous_engine.py 改造
async def _notify_circuit_breaker(self, account_id: str, pnl: float, equity: float):
    await notification_service.send_telegram(
        f"⚡ 熔断触发｜账户 {account_id}\n"
        f"日内亏损: {pnl:+.2f} ({pnl/equity*100:.1f}%)\n"
        f"AI 自动交易已暂停，请检查"
    )

async def _notify_suggestion(self, account_id: str, decision: dict):
    # ADVISORY 模式：AI 建议等待人工确认
    await notification_service.send_telegram(
        f"🤖 AI 建议待确认｜{decision['symbol']}\n"
        f"操作: {decision['action']}  数量: {decision['qty']}\n"
        f"置信度: {decision['confidence']*100:.0f}%\n"
        f"[确认执行] {settings.FRONTEND_URL}/copilot?action={action_id}"
    )
```

**SEMI 模式撤销窗口**需同步完善：
```
执行 → 写 revoke_token（30min TTL）→ Telegram 推送含撤销链接
用户点击 → POST /api/v1/autonomy/revoke/{exec_id} → 反向平仓
```

**验收标准**：
- [ ] SEMI 模式每次 AI 执行后发送 Telegram 消息，含撤销链接
- [ ] FULL 模式熔断时立即推送 Telegram 告警
- [ ] 撤销窗口 30 分钟后 token 失效，数据库记录 `revoked_at`

---

### 1.3 Copilot 操作指令执行落地

**问题**：`copilot_service.py` L137/140/143 三处 TODO 导致 Copilot 检测到"修改止损""TWAP下单""清仓"意图后只返回解析结果，不实际执行。

**改造**：

| 意图类型 | 当前状态 | V10.1 目标 |
|---------|---------|-----------|
| `MODIFY_STOP` | TODO | 调用 `order_service.modify_stop_loss(symbol, new_stop)` |
| `SUBMIT_ALGO_ORDER` | TODO | 调用 `twap_vwap_service.submit(symbol, side, qty, algo)` |
| `CLOSE_ALL_POSITIONS` | TODO | 调用 `position_service.close_all(account_id)` → 逐仓平仓 |
| `TOGGLE_AUTONOMY` | ✅ 已实现 | 保持 |
| `PAUSE_TRADING` | ✅ 已实现 | 保持 |

**UI 配合**：前端 `CopilotPage.vue` 在 `action_intent != null` 时渲染确认对话框，用户点击确认后调 `POST /api/v1/copilot/confirm/{action_id}`，后端再实际执行。

**验收标准**：
- [ ] Copilot 可通过自然语言完成止损价修改
- [ ] Copilot 可提交 TWAP/VWAP 任务并返回 task_id
- [ ] 清仓指令需二次确认，执行后推 Telegram 通知

---

## 2. P1 — 仪表盘数据真实性

> **目标**：消除 `dashboard_v2_service.py` 中所有 `# TODO` 占位，让仪表盘数字可信

### 2.1 风险指标实时计算

**问题**：`_get_risk_metrics()` L331 注释"TODO: 计算 VaR、最大回撤等指标"，当前返回空字典。

**实现**：复用已有的 `var_calculator.py` 和 `stress_test_service.py`：

```python
async def _get_risk_metrics(self, account_id: str) -> dict:
    var_result = await var_calculator.compute_var(account_id)
    max_dd = await equity_service.get_max_drawdown(account_id, days=30)
    return {
        "var_95": var_result.var_pct,
        "var_dollar": var_result.var_dollar,
        "max_drawdown_30d": max_dd,
        "circuit_breaker_status": await _get_circuit_breaker_status(account_id),
    }
```

### 2.2 宏观风险接入仪表盘

**问题**：`_get_macro_overview()` L356 注释"TODO: 从宏观风险表读取"，当前返回默认值。

**实现**：调用 `macro_risk_scoring_service.get_latest_score(account_id)` （服务已存在）。

### 2.3 执行指标（滑点 + 取消率）

**问题**：`_get_execution_metrics()` L535 注释"TODO: 计算取消数和滑点"。

**实现**：
- 从 `algo_execution_tasks` 表聚合：`filled/total` 完成率、`avg_price - benchmark_price` 滑点
- 加入缓存 TTL = 5min

### 2.4 策略运行统计 + API 监控 + 市场热点

| TODO 位置 | 实现方案 |
|----------|---------|
| L655 策略运行统计 | 查询 `strategy_runs` 表：今日运行次数、信号产出量 |
| L661 API 监控 | 调用已有 `api_monitoring_service.get_today_summary()` |
| L666 系统错误统计 | 查询 `audit_logs` + 应用日志中的 ERROR 行数 |
| L672 市场热点 | 调用 `market_hotspot_service.get_latest_hotspots()` |

**验收标准**：
- [ ] Dashboard `/api/v1/dashboard/v2/full` 返回中无 `null` 的关键指标字段
- [ ] VaR 水位、宏观风险评分正常显示
- [ ] 滑点监控有实际数据（哪怕是 Paper 模式的模拟数据）

---

## 3. P2 — AI 决策质量提升

### 3.1 组合级决策（Portfolio-Level Decision）

**问题**：V10.0 的 `AutonomousEngine._ai_decide()` 是**逐条信号**独立调 AI，存在：
- 忽略跨标的相关性，可能重复持有高相关资产
- AI 每次只看单个信号，无全局视野
- 未充分利用已有的 `PortfolioOptimizer`

**V10.1 改造**：单次决策循环改为批量决策

```python
# V10.0 (逐条)
for signal in pending_signals:
    decision = await self._ai_decide(signal, positions, equity)

# V10.1 (批量)
portfolio_context = await portfolio_optimizer.get_current_state(account_id)
batch_decisions = await self._ai_decide_portfolio(
    signals=pending_signals,
    positions=positions,
    equity=equity,
    portfolio_context=portfolio_context,   # 相关性矩阵、当前权重
)
```

**AI Prompt 升级**：从单标的 prompt 升级为组合视角 prompt，引入：
- 当前持仓分布与目标权重差值
- 各候选信号之间的相关系数矩阵
- Kelly 建议仓位 vs Markowitz 约束调整结果

### 3.2 AI 结构化输出（消除 Regex 解析）

**问题**：`autonomous_engine.py` 和 `copilot_service.py` 中多处使用 `re.search(r"\{.*\}", ...)` 提取 AI 返回的 JSON，不稳定且维护成本高。

**V10.1 改造**：统一使用 OpenAI / DeepSeek 的结构化输出接口

```python
# V10.1: 使用 response_format={"type": "json_object"}
resp = await client.chat.completions.create(
    model=model,
    messages=[...],
    response_format={"type": "json_object"},   # 强制 JSON 输出
    max_tokens=1500,
)
# 不再需要 regex 提取
decision = json.loads(resp.choices[0].message.content)
```

**涉及改造点**：
- `autonomous_engine._call_ai()` - 决策调用
- `copilot_service._detect_intent()` - 意图解析
- `ai_trade_advisor_service._generate_ai_decision()` - AI 交易建议

### 3.3 技术分析指标修复

**问题**：`technical_analysis_service.py` L374 布林带宽度百分位硬编码为 `65`，不反映真实市场位置。

**实现**：基于近 252 日历史布林带宽度计算真实百分位：

```python
# 计算真实 Bollinger Band Width Percentile
historical_widths = [abs(upper - lower) / middle for upper, middle, lower in hist_bb]
current_width = abs(bb_upper - bb_middle) / bb_middle
width_percentile = int(
    sum(1 for w in historical_widths if w <= current_width) / len(historical_widths) * 100
)
```

### 3.4 Paper→Live 自动毕业流程完整闭环

**V10.0 状态**：`BacktestRunner._check_graduation()` 已实现毕业判断逻辑，但：
- Paper 账户满 30 天自动触发回测验证的定时任务未注册
- 通过回测后自动升级 Live 的逻辑未接入 `jobs/`

**V10.1 补全**：

```python
# jobs/paper_graduation_job.py (新增)
async def check_paper_graduation():
    """每日 23:00 检查达标策略，自动触发毕业回测"""
    candidates = await paper_trading_service.get_graduation_candidates()
    for strategy in candidates:
        task = await backtest_service.run_walk_forward(strategy)
        if backtest_runner._check_graduation(task.result):
            await paper_trading_service.graduate_to_live(strategy.id)
            await notification_service.send_telegram(
                f"🎓 策略升级通知｜{strategy.name}\n"
                f"Sharpe: {task.result['sharpe']:.2f}  胜率: {task.result['win_rate']*100:.0f}%\n"
                f"已从 Paper 升级为 Live（首月 25% 仓位）"
            )
```

---

## 4. P3 — 扩展标的边界

> V10.0 路线图 Phase 10 的直接落地，个人系统扩大可投资宇宙

### 4.1 ETF 标的支持（`STOCK,ETF` 模式）

**背景**：行业轮动策略（`sector_rotation.py`）和 CTA 商品策略（`cta_commodities.py`）已在 V10 中实现，但需要 ETF 标的才能真正运行。

**改造范围**：

| 模块 | 改造内容 |
|------|---------|
| `config.py` | `ALLOWED_ASSET_TYPES=STOCK,ETF` 中 `ETF` 正式支持 |
| `signal_position_filter.py` | 放行 ETF 类型标的通过风险门 |
| `data/hub.py` | DataHub 增加 ETF 专项处理（分红调整、AUM 数据） |
| `strategies/sector_rotation.py` | 接入真实 ETF 代码库（SPY/QQQ/XLK 等）|
| `strategies/cta_commodities.py` | 接入商品 ETF（GLD/SLV/USO/DBC 等）|
| `paper_trading_service.py` | ETF 成交模拟（无期权 Greeks，无借贷限制）|

**初始 ETF 标的池**：

```python
DEFAULT_ETF_POOL = {
    "broad_market": ["SPY", "QQQ", "IWM", "DIA"],
    "sector": ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB", "XLRE"],
    "thematic": ["ARKK", "QLD", "TQQQ"],  # 仅 ADVISORY 模式允许杠杆 ETF
    "commodity": ["GLD", "SLV", "USO", "DBC", "UNG"],
    "bond": ["TLT", "IEF", "SHY", "HYG"],
    "international": ["EFA", "EEM", "FXI"],
}
```

**验收标准**：
- [ ] `ALLOWED_ASSET_TYPES=STOCK,ETF` 时，`sector_rotation` 和 `cta_commodities` 策略正常产生信号
- [ ] ETF 标的可进入 Markowitz 组合优化
- [ ] Dashboard 持仓视图区分 STOCK / ETF 类型
- [ ] 杠杆/反向 ETF 需特殊标记，默认不进入 FULL 模式自动执行

### 4.2 港股标的接入（统一 Tiger API）

**原则**：港股行情与交易完全通过老虎证券 API 获取，与美股股票保持一致，**不引入 Futu API**，维持单一 broker 客户端架构，降低维护复杂度。

Tiger API 本身已支持：
- 港股实时/延迟行情（`Market.HK`）
- 港股持仓查询（`list_positions`）
- 港股下单（`Market.HK` + `SecurityType.STK`）
- 期权行情与下单（`SecurityType.OPT`，美股期权）

**改造范围**（复用现有 Tiger 客户端，不新增 broker 文件）：

```
app/broker/
  └── tiger_option_client.py   # 扩展：list_hk_positions / submit_hk_order
                               # （Market.HK 参数传入，逻辑复用现有 US 路径）

app/data/hub.py                # DataHub 港股行情节点：Tiger(HK) → yfinance 降级
app/core/config.py             # 新增 ALLOWED_MARKETS (US,HK) 配置
```

**港股标的识别规则**：
```python
def is_hk_stock(symbol: str) -> bool:
    # 支持格式："00700.HK" / "0700.HK" / 纯数字 "700"（自动补零至 5 位）
    return symbol.upper().endswith(".HK") or (symbol.isdigit() and len(symbol) <= 5)

def normalize_hk_symbol(symbol: str) -> str:
    """统一转为 Tiger API 格式，如 '700' -> '00700'"""
    if symbol.isdigit():
        return symbol.zfill(5)
    return symbol.split(".")[0].zfill(5)  # 去掉 .HK 后缀，补前导零
```

**DataHub 路由逻辑**：
```
美股标的（无后缀 / .US）→ Tiger(US) → yfinance 降级
港股标的（.HK / 纯数字） → Tiger(HK) → 无完整降级（yfinance 港股数据质量差）
期权标的（含 OPT 字段）  → Tiger(OPT) → 不降级（期权数据无 yfinance 来源）
```

**验收标准**：
- [ ] `GET /api/v1/positions` 港股持仓通过 Tiger API 正常显示（`Market.HK`）
- [ ] AI 决策支持港股标的（`00700.HK` / `09988.HK`）
- [ ] Paper 模式港股模拟成交正常（使用 Tiger 延迟行情作为参考价）
- [ ] 期权行情（IV、Greeks、链报价）通过现有 `TigerOptionClient` 获取，无需改动

---

## 5. P4 — 可观测性与稳定性

### 5.1 Dashboard WebSocket 实时推送

**问题**：前端 `DashboardV2Page.vue` 每 30s 轮询 HTTP，价格敏感场景下数据延迟明显。

**改造**：
- 后端：在 `main.py` 添加 WebSocket 端点 `WS /ws/dashboard/{account_id}`
- 触发机制：订单成交 / 策略信号生成 / 价格告警触发 → 推送增量更新
- 前端：降级策略——WebSocket 不可用时回退到 30s 轮询

```python
# backend: routers/ws.py (新增)
@router.websocket("/ws/dashboard/{account_id}")
async def dashboard_ws(ws: WebSocket, account_id: str):
    await ws.accept()
    last_state = {}
    while True:
        new_state = await dashboard_service.get_quick_kpi(account_id)
        delta = compute_delta(last_state, new_state)
        if delta:
            await ws.send_json(delta)
            last_state = new_state
        await asyncio.sleep(5)   # 5s 心跳
```

### 5.2 端到端集成测试

**V10.0 缺失**：核心闭环（策略运行 → 信号生成 → 风险门禁 → Paper 下单 → 审计日志）缺少自动化集成测试。

**新增测试规划**：

```
tests/integration/
  ├── test_autonomous_loop.py    # SEMI 模式完整闭环（Mock Tiger + Mock AI）
  ├── test_risk_gate.py          # VaR 超限 → 拒绝执行 → 日志记录
  ├── test_paper_graduation.py   # Walk-Forward 通过 → Paper 毕业通知
  ├── test_copilot_actions.py    # Copilot 意图解析 → 执行 → 验证
  └── test_twap_execution.py     # TWAP 6片拆分 → 全部成交 → 状态汇总
```

**目标覆盖率**：核心引擎（engine/）≥ 80%，服务层（services/）≥ 65%

### 5.3 AI 决策可观测性增强

**增加专项仪表盘指标**（`AutonomyPage.vue` 扩展）：

| 指标 | 数据来源 | 说明 |
|------|---------|------|
| AI 本周决策胜率 | `autonomy_audit_log` | 已平仓信号的盈亏统计 |
| 风险门拒绝率 | `autonomy_audit_log.risk_gate_passed=0` | 多少决策被门控拦截 |
| 平均决策置信度 | `autonomy_audit_log.confidence_score` | 近 30 天均值 |
| 熔断触发次数 | `circuit_breaker_triggered=1` | 当月统计 |
| Paper vs Live 收益差 | `equity_snapshots` 按 account_type | 两轨对比 |

### 5.4 智能订单路由 Tiger 集成

**问题**：`smart_order_router.py` L285 注释"TODO: 集成 Tiger Broker API"。该文件负责根据标的类型（股票/ETF/期权）选择最优执行路径，但实际下单逻辑缺失。

**与 P0.1 协同**：`smart_order_router.py` 调用 `TigerOrderExecutor`（P0.1 完成后），增加路由层：

```python
class SmartOrderRouter:
    async def route_and_execute(self, order: dict) -> dict:
        # 美股/港股/期权统一走 Tiger；market 字段区分 US / HK
        executor = self._select_executor(order)
        return await executor.submit_order(order)

    def _select_executor(self, order: dict) -> OrderExecutor:
        value = order["quantity"] * order.get("price", 100)
        equity = order.get("account_equity", 100_000)
        ratio = value / equity
        if ratio < 0.01:   return MarketOrderExecutor()
        if ratio < 0.05:   return VwapExecutor(duration=30)
        return TwapExecutor(duration=60, slices=6)
```

---

## 6. 性能要求（V10.1 基准）

| 指标 | V10.0 设计目标 | V10.1 目标 |
|------|--------------|-----------|
| AI 组合级决策（含组合优化）| P95 < 8s | P95 < 10s（批量信号更复杂）|
| Dashboard WebSocket 增量推送延迟 | N/A（轮询 30s）| < 5s |
| Tiger 下单 → 成交确认 | N/A（未实现）| P95 < 3s |
| 回测任务（2年日线，1策略）| < 30s | < 30s（保持）|
| API 端点（非 AI）| P95 < 500ms | P95 < 500ms（保持）|

---

## 7. 数据库变更（V10.1 新增）

### 7.1 新增字段

```sql
-- autonomy_audit_log 新增字段：组合决策批次 ID
ALTER TABLE autonomy_audit_log 
  ADD COLUMN batch_decision_id VARCHAR(64) NULL COMMENT 'V10.1: 组合级决策批次ID';

-- trading_plans 新增字段：ETF 类型标识
ALTER TABLE trading_plans 
  ADD COLUMN asset_type VARCHAR(16) NOT NULL DEFAULT 'STOCK' COMMENT 'STOCK/ETF/OPTION';
```

### 7.2 新增表

```sql
-- etf_watchlist：ETF 标的池管理
CREATE TABLE etf_watchlist (
  id INT PRIMARY KEY AUTO_INCREMENT,
  symbol VARCHAR(32) NOT NULL UNIQUE,
  category VARCHAR(32) COMMENT 'broad_market/sector/commodity/bond/thematic',
  name VARCHAR(128),
  leverage_factor DECIMAL(4,2) DEFAULT 1.0 COMMENT '1.0=标准, 2.0=2倍, -1.0=反向',
  is_leveraged BOOLEAN GENERATED ALWAYS AS (leverage_factor != 1.0) STORED,
  allowed_in_full_mode BOOLEAN DEFAULT TRUE,
  enabled BOOLEAN DEFAULT TRUE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- tiger_hk_order_ext：港股订单 market 字段扩展（Tiger 统一管理）
ALTER TABLE algo_execution_tasks
  ADD COLUMN market VARCHAR(8) NOT NULL DEFAULT 'US' COMMENT 'US / HK';
```

---

## 8. 前端变更（V10.1）

### 8.1 新增/修改组件

| 组件 | 变更类型 | 说明 |
|------|---------|------|
| `DashboardV2Page.vue` | 改造 | WebSocket 订阅（降级到轮询）；VaR 水位、宏观风险、热点数据真实显示 |
| `AutonomyPage.vue` | 增强 | AI 决策胜率、风险门拒绝率、置信度趋势图 |
| `CopilotPage.vue` | 增强 | 操作意图确认对话框（`action_intent` 弹窗确认） |
| `PortfolioPage.vue` | 增强 | 组合级 AI 决策历史（batch_decision_id 聚合）|
| `StrategiesPage.vue` | 增强 | ETF/港股标的池配置入口 |
| `ETFWatchlistPanel.vue` | 新增 | ETF 标的池管理（分组显示、杠杆 ETF 特殊标记）|
| `PositionsPage.vue` | 增强 | 港股持仓视图（通过 Tiger API，与美股持仓统一展示，市场标签 US/HK 区分）|

### 8.2 路由新增

```
/etf-watchlist     ETF 标的池管理
/hk-positions      港股持仓专页（可选，或集成到 /positions）
```

---

## 9. 版本里程碑

| 里程碑 | 目标完成时间 | 关键交付物 |
|--------|------------|---------|
| **M1: 执行闭环** | W1-W2 | Tiger 真实下单可用；Telegram SEMI 模式通知正常 |
| **M2: 仪表盘真实化** | W2-W3 | Dashboard 无 TODO 占位，所有指标有真实数据 |
| **M3: Copilot 指令落地** | W3 | 修改止损 / TWAP 下单 / 清仓 三类指令可通过 Copilot 执行 |
| **M4: AI 决策升级** | W3-W4 | 组合级批量决策上线；结构化 JSON 输出消除 regex |
| **M5: ETF 支持** | W4-W5 | `STOCK,ETF` 模式：行业轮动 + CTA 策略正常运行 |
| **M6: Paper 毕业流程** | W5 | 自动毕业定时任务注册；毕业事件写入系统日志 |
| **M7: 港股支持（Tiger API）** | W5-W6 | Tiger(HK) 行情路由；Paper 模式港股模拟可用 |
| **M8: WebSocket + 集成测试** | W6 | Dashboard 实时推送；核心路径集成测试覆盖 ≥ 65% |
| **版本发布** | W7 | V10.1 全量发布，更新文档 |

---

## 10. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|-----|------|------|
| Tiger API 港股行情延迟（免费 15min 延迟） | 中 | 低 | 开发/测试用 DELAYED 模式；实盘需申请 REALTIME 订阅；Paper 模式使用延迟行情模拟成交 |
| Tiger API 港股数据覆盖不全（冷门小盘） | 中 | 低 | 仅支持港股主板 + 科技板主要标的；覆盖范围在 `DEFAULT_HK_UNIVERSE` 中显式配置 |
| DeepSeek/OpenAI JSON 结构化输出不稳定 | 中 | 中 | 保留 regex 解析作为 fallback，不完全移除 |
| 组合级 AI 决策 Prompt 长度超限 | 中 | 中 | 信号超过 10 个时分批处理，每批 ≤ 10 个标的 |
| Tiger 真实下单出现 Fat Finger | 低 | 高 | P0.1 内保留 `OrderSafetyGuard` 及 DRY_RUN 开关，上线前强制 Paper 验证 |

---

## 11. 与 V11 边界划定

**V10.1 不做**（留给 V11）：

| 功能 | 理由 |
|------|------|
| 期权执行（`STOCK,ETF,OPTION` 全模式）| 期权行情已通过 Tiger API 支持（只读），执行风险高，需完整 Greeks 实时对冲方案，V11 专项规划 |
| 多账户支持 | 当前个人交易账户为单一 `account_id`，多账户带来架构复杂度 |
| LLM Fine-tuning 个人交易风格 | 数据积累不足，需 V11 版本充分运行后再启动 |
| 实时 L2 订单簿分析 | Tiger API 限速，L2 数据成本高，个人账户意义有限 |
| 移动端原生 App | Web 端已支持响应式，个人系统优先级不高 |
| Futu OpenD 接入 | Tiger API 已完整覆盖美股/港股/期权行情与下单，引入 Futu 带来额外维护负担，本系统不采用 |

---

## 附录 A：V10.0 已知问题完整清单

| 文件 | 行号 | 类型 | 描述 |
|------|-----|------|------|
| `order_service.py` | L79-85 | 未实现 | Tiger 真实下单/取消/查询 |
| `autonomous_engine.py` | L248/254 | TODO | Telegram 通知未接入 |
| `copilot_service.py` | L137/140/143 | TODO | 三类操作指令未执行 |
| `dashboard_v2_service.py` | L331 | TODO | VaR/最大回撤计算 |
| `dashboard_v2_service.py` | L356 | TODO | 宏观风险表读取 |
| `dashboard_v2_service.py` | L535 | TODO | 执行指标（取消数/滑点）|
| `dashboard_v2_service.py` | L561 | TODO | target_price 从 plan_details 提取 |
| `dashboard_v2_service.py` | L655/661/666/672 | TODO | 策略统计/API监控/错误统计/热点 |
| `technical_analysis_service.py` | L374 | 硬编码 | Bollinger 宽度百分位固定为 65 |
| `smart_order_router.py` | L285 | TODO | Tiger 下单路由未集成 |
| `option_exposure_service.py` | L122 | TODO | Gamma/Vega/Theta 估算缺失 |

---

## 附录 B：关键配置项变更

```bash
# V10.1 新增配置项

# 港股 & 期权市场支持（P3.2）——统一走 Tiger API，无需 Futu
ALLOWED_MARKETS=US,HK           # US / US,HK（开启港股）
# 港股行情使用 Tiger DELAYED 或 REALTIME，与 TIGER_QUOTE_MODE 共用同一配置
# 期权行情同样使用现有 TigerOptionClient，无需额外配置

# ETF 支持（P3.1）
ALLOWED_ASSET_TYPES=STOCK,ETF   # 默认值从 STOCK 升级
ALLOW_LEVERAGED_ETF=false        # 杠杆/反向 ETF 在 FULL 模式下是否允许

# WebSocket（P4.1）
WS_DASHBOARD_ENABLED=true
WS_HEARTBEAT_INTERVAL=5         # 秒

# AI 结构化输出（P2.2）
AI_USE_JSON_MODE=true            # 启用 OpenAI/DeepSeek JSON mode
```

---

*文档维护人：系统开发者 | 下次评审：V10.1-M4 完成后*
