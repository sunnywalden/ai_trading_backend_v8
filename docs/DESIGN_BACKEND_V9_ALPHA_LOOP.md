# 后端系统设计文档 V9 — Alpha Loop

> 依赖项目：ai_trading_backend_v8/backend
> 文档版本：v9.0
> 日期：2026-02-09
> 依赖：PRD_V9_ALPHA_LOOP.md

---

## 1. 架构升级概览

### 1.1 新增模块

```
backend/app/
├── engine/
│   ├── auto_hedge_engine.py      # 已有
│   ├── signal_engine.py          # NEW: 信号引擎
│   ├── backtest_engine.py        # NEW: 回测引擎
│   ├── alert_engine.py           # NEW: 价格告警引擎
│   └── order_executor.py         # NEW: 订单执行器
├── factors/                       # NEW: 因子库
│   ├── base.py
│   ├── momentum.py
│   ├── mean_reversion.py
│   ├── volume.py
│   └── fundamental.py
├── models/
│   ├── equity_snapshot.py         # NEW
│   ├── trade_journal.py           # NEW
│   ├── price_alert.py             # NEW
│   ├── audit_log.py               # NEW
│   ├── notification.py            # NEW
│   └── ... (existing)
├── services/
│   ├── dashboard_service.py       # NEW
│   ├── equity_service.py          # NEW
│   ├── journal_service.py         # NEW
│   ├── alert_service.py           # NEW
│   ├── order_service.py           # NEW
│   ├── notification_service.py    # NEW
│   └── ... (existing)
├── routers/
│   ├── dashboard.py               # NEW
│   ├── equity.py                  # NEW
│   ├── journal.py                 # NEW
│   ├── alerts.py                  # NEW
│   ├── orders.py                  # NEW
│   ├── websocket.py               # NEW
│   └── ... (existing)
└── schemas/
    ├── dashboard.py               # NEW
    ├── equity.py                  # NEW
    ├── journal.py                 # NEW
    ├── alerts.py                  # NEW
    ├── orders.py                  # NEW
    └── ... (existing)
```

### 1.2 事件驱动架构

```
MarketDataProvider ──▶ Redis PubSub ──▶ AlertEngine (价格检测)
                                    ──▶ SignalEngine (因子计算)
                                    ──▶ WebSocket Hub (前端推送)

AlertEngine ──▶ NotificationService ──▶ WebSocket / Telegram
SignalEngine ──▶ NotificationService ──▶ WebSocket
OrderExecutor ──▶ AuditLog + NotificationService
```

---

## 2. 数据模型（新增 7 张表）

### 2.1 equity_snapshots — 账户权益快照

```sql
CREATE TABLE equity_snapshots (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  snapshot_date DATE NOT NULL,
  total_equity DECIMAL(20, 2) NOT NULL,
  cash DECIMAL(20, 2) NOT NULL DEFAULT 0,
  market_value DECIMAL(20, 2) NOT NULL DEFAULT 0,
  realized_pnl DECIMAL(20, 2) NOT NULL DEFAULT 0,
  unrealized_pnl DECIMAL(20, 2) NOT NULL DEFAULT 0,
  daily_return DECIMAL(10, 6) DEFAULT NULL,
  cumulative_return DECIMAL(10, 6) DEFAULT NULL,
  max_drawdown_pct DECIMAL(10, 6) DEFAULT NULL,
  benchmark_return DECIMAL(10, 6) DEFAULT NULL COMMENT 'SPY daily return',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_account_date (account_id, snapshot_date),
  INDEX idx_account_date (account_id, snapshot_date)
);
```

### 2.2 trade_pnl_attribution — 交易盈亏归因

```sql
CREATE TABLE trade_pnl_attribution (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  trade_date DATE NOT NULL,
  direction VARCHAR(8) NOT NULL COMMENT 'LONG/SHORT',
  entry_price DECIMAL(20, 6) NOT NULL,
  exit_price DECIMAL(20, 6) DEFAULT NULL,
  quantity DECIMAL(20, 6) NOT NULL,
  realized_pnl DECIMAL(20, 2) DEFAULT NULL,
  holding_days INT DEFAULT NULL,
  strategy_tag VARCHAR(64) DEFAULT NULL,
  factor_tag VARCHAR(64) DEFAULT NULL,
  plan_id INT DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_date (account_id, trade_date),
  INDEX idx_symbol (symbol)
);
```

### 2.3 trade_journal — 交易日志/复盘

```sql
CREATE TABLE trade_journal (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  direction VARCHAR(8) NOT NULL,
  entry_date DATE DEFAULT NULL,
  exit_date DATE DEFAULT NULL,
  entry_price DECIMAL(20, 6) DEFAULT NULL,
  exit_price DECIMAL(20, 6) DEFAULT NULL,
  quantity DECIMAL(20, 6) DEFAULT NULL,
  realized_pnl DECIMAL(20, 2) DEFAULT NULL,
  plan_id INT DEFAULT NULL,
  execution_quality INT DEFAULT NULL COMMENT '1-5 self-rating',
  emotion_state VARCHAR(16) DEFAULT NULL COMMENT 'calm/anxious/revenge/fomo/greedy',
  mistake_tags JSON DEFAULT NULL COMMENT '["sell_fly","chase_high"]',
  lesson_learned TEXT DEFAULT NULL,
  ai_review TEXT DEFAULT NULL,
  journal_status VARCHAR(16) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT/COMPLETED/REVIEWED',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_account_date (account_id, entry_date),
  INDEX idx_symbol (symbol)
);
```

### 2.4 price_alerts — 价格告警规则

```sql
CREATE TABLE price_alerts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  condition_type VARCHAR(32) NOT NULL COMMENT 'price_above/price_below/pct_change/rsi_cross/macd_cross',
  threshold DECIMAL(20, 6) NOT NULL,
  action VARCHAR(16) NOT NULL DEFAULT 'notify' COMMENT 'notify/auto_execute',
  linked_plan_id INT DEFAULT NULL,
  alert_status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE/PAUSED/TRIGGERED/EXPIRED',
  triggered_at DATETIME DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_account_status (account_id, alert_status),
  INDEX idx_symbol (symbol)
);
```

### 2.5 alert_history — 告警触发历史

```sql
CREATE TABLE alert_history (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  alert_id BIGINT NOT NULL,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  trigger_price DECIMAL(20, 6) NOT NULL,
  trigger_time DATETIME NOT NULL,
  notification_sent BOOLEAN NOT NULL DEFAULT FALSE,
  action_taken VARCHAR(64) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_time (account_id, trigger_time),
  INDEX idx_alert (alert_id)
);
```

### 2.6 audit_logs — 审计日志

```sql
CREATE TABLE audit_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id VARCHAR(64) NOT NULL,
  action VARCHAR(64) NOT NULL,
  resource VARCHAR(128) NOT NULL,
  payload JSON DEFAULT NULL,
  ip_address VARCHAR(45) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user_time (user_id, created_at),
  INDEX idx_action (action)
);
```

### 2.7 notification_log — 通知记录

```sql
CREATE TABLE notification_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  channel VARCHAR(16) NOT NULL COMMENT 'websocket/telegram/email/desktop',
  event_type VARCHAR(32) NOT NULL,
  title VARCHAR(128) NOT NULL,
  body TEXT DEFAULT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'SENT' COMMENT 'SENT/FAILED/READ',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_time (account_id, created_at)
);
```

---

## 3. API 设计

### 3.1 Dashboard API

```
GET /api/v1/dashboard/summary
  Response: {
    account_id, total_equity, cash, market_value,
    daily_pnl, daily_return_pct,
    mtd_return_pct, ytd_return_pct,
    plan_execution_rate, active_plans_count,
    risk_level, exposure: { delta_pct, gamma_pct, vega_pct, theta_pct },
    recent_signals: [...],
    pending_actions: [...]
  }
```

### 3.2 Equity API

```
GET /api/v1/equity/snapshots?days=30
  Response: { snapshots: [{ date, equity, daily_return, cumulative_return, benchmark_return }] }

GET /api/v1/equity/pnl-attribution?start_date=...&end_date=...&group_by=symbol|strategy
  Response: { attributions: [{ label, pnl, pct }] }

POST /api/v1/equity/snapshot
  Description: 手动触发当日快照
```

### 3.3 Journal API

```
GET /api/v1/journal/list?page=1&size=20&symbol=...&status=...
POST /api/v1/journal/create  { symbol, direction, entry_date, ... }
PATCH /api/v1/journal/{id}  { execution_quality, emotion_state, mistake_tags, ... }
POST /api/v1/journal/{id}/ai-review
  Description: 触发 GPT AI 复盘
  Response: { ai_review: "..." }
GET /api/v1/journal/weekly-report?date=2026-02-09
  Description: AI 周报
```

### 3.4 Alert API

```
GET /api/v1/alerts/list?status=ACTIVE
POST /api/v1/alerts/create  { symbol, condition_type, threshold, action, linked_plan_id }
PATCH /api/v1/alerts/{id}  { threshold, action, alert_status }
DELETE /api/v1/alerts/{id}
GET /api/v1/alerts/history?limit=20
```

### 3.5 Order API

```
POST /api/v1/orders/submit  { symbol, direction, quantity, order_type, limit_price, plan_id }
GET /api/v1/orders/{id}/status
POST /api/v1/orders/{id}/cancel
GET /api/v1/orders/history?limit=20
```

### 3.6 WebSocket

```
WS /ws/trading?token=<jwt>
  Channels: price_alert, signal_fired, order_update, risk_warning, equity_update
  Format: { channel, event, data, timestamp }
```

### 3.7 Backtest API

```
POST /api/v1/backtest/run  { strategy_id, start_date, end_date, initial_capital, params }
GET /api/v1/backtest/results/{id}
  Response: { equity_curve, trades, metrics: { sharpe, sortino, max_dd, win_rate, profit_factor } }
```

---

## 4. 核心服务设计

### 4.1 DashboardService

聚合多个数据源为 Dashboard 摘要：
- AccountService → 权益/现金
- EquityService → 今日盈亏/MTD/YTD
- TradingPlanService → 计划执行率
- OptionExposureService → Greeks 水位
- AlertService → 最近触发的告警
- SignalEngine → 最新信号

### 4.2 EquityService

- `create_daily_snapshot()`：从 AccountService 获取当日权益 → 计算日收益率 → 写入 DB
- `get_snapshots(days)`：查询历史快照
- `get_pnl_attribution()`：从 trade_pnl_attribution 聚合

### 4.3 JournalService

- CRUD 交易日志
- `ai_review(journal_id)`：聚合交易数据 + 技术指标 → GPT 生成复盘
- `weekly_report(date)`：聚合周内所有日志 → GPT 生成周报

### 4.4 AlertService

- `create_alert()`：创建告警规则
- `check_alerts()`：遍历活跃告警 → 对比当前价格 → 触发匹配的告警
- `on_alert_triggered()`：记录历史 + 发送通知 + 可选自动执行

### 4.5 OrderService

- `submit_order()`：验证 → SafetyGuard 检查 → 熔断检查 → 执行
- `cancel_order()`
- `get_status()`

### 4.6 NotificationService

- `send(channel, event_type, title, body)`
- 支持 WebSocket / Telegram / 桌面
- 自动记录 notification_log

### 4.7 SignalEngine

- 加载因子库 → 计算因子值 → 聚合信号 → 过滤
- 输出：`Signal { symbol, direction, strength, factors, win_rate, rr_ratio }`

### 4.8 BacktestEngine

- 事件驱动：OnBar → 策略 → OrderEvent → Portfolio
- 输出：净值曲线、交易列表、绩效指标

---

## 5. 定时任务新增

| 任务 | 频率 | 功能 |
|------|------|------|
| `equity_snapshot_job` | 每日 16:30 ET | 采集当日账户权益快照 |
| `alert_check_job` | 每 30s | 检查价格告警 |
| `daily_loss_check_job` | 每 5min（交易时段） | 检查日亏损是否触发熔断 |

---

## 6. 安全加固

### 6.1 密码安全

```python
# auth.py 改造
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def authenticate_user(username, password):
    if username != settings.ADMIN_USERNAME:
        return False
    return pwd_context.verify(password, settings.ADMIN_PASSWORD_HASH)
```

### 6.2 JWT 强校验

```python
# config.py
JWT_SECRET_KEY: str = "change-me-please"

# main.py startup
if settings.JWT_SECRET_KEY == "change-me-please":
    import warnings
    warnings.warn("⚠️ JWT_SECRET_KEY is default value! Change it in production!")
```

### 6.3 订单安全

```python
class OrderSafetyGuard:
    max_orders_per_minute: int = 5
    max_single_order_pct: float = 0.2  # 单笔不超过净值20%
    daily_loss_limit_pct: float = 0.05  # 日亏损5%熔断
    trading_hours_only: bool = True     # 仅交易时段
```

---

## 7. WebSocket 实现

```python
# routers/websocket.py
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    async def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)

    async def broadcast(self, channel: str, data: dict):
        message = {"channel": channel, "data": data, "timestamp": datetime.utcnow().isoformat()}
        for ws in self.active_connections.values():
            try:
                await ws.send_json(message)
            except:
                pass

manager = ConnectionManager()
```

---

## 8. 配置扩展

```python
# config.py 新增
TELEGRAM_BOT_TOKEN: str | None = None
TELEGRAM_CHAT_ID: str | None = None
ADMIN_PASSWORD_HASH: str = "$2b$12$..."  # bcrypt hash
ORDER_MODE: str = "PAPER"  # PAPER / REAL
MAX_DAILY_LOSS_PCT: float = 0.05
MAX_ORDERS_PER_MINUTE: int = 5
ALERT_CHECK_INTERVAL_SECONDS: int = 30
EQUITY_SNAPSHOT_TIME: str = "16:30"  # ET
WS_HEARTBEAT_SECONDS: int = 30
```

---

## 9. 测试计划

| 模块 | 测试类型 | 覆盖 |
|------|---------|------|
| EquityService | Unit | 快照计算/收益率/回撤 |
| JournalService | Unit | CRUD + AI 复盘 |
| AlertService | Unit + Integration | 告警创建/触发/通知 |
| OrderService | Unit + Integration | 提交/安全检查/熔断 |
| SignalEngine | Unit | 因子计算/信号聚合 |
| BacktestEngine | Unit | 回测流程/指标计算 |
| WebSocket | Integration | 连接/推送/重连 |
| Dashboard API | Integration | 聚合数据完整性 |

---

**文档维护者**：AI Trading Team  
**最后更新**：2026-02-09
