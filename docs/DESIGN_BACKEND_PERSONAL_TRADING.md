# 后端详细实现设计文档（个人交易版）

> 依赖项目：`ai_trading_backend_v8/backend`
> 文档版本：v1.0
> 日期：2026-01-16

---

## 1. 设计目标

- 支撑个人交易闭环：计划 → 执行 → 复盘
- 简化与现有模块对齐：复用持仓评估/机会扫描/宏观风险
- 提供可扩展的“计划模型”和“纪律评分”

---

## 2. 总体架构

- FastAPI + SQLAlchemy Async
- 模块化 Router：`positions/macro/opportunities/monitoring/plan`
- Service 层：交易计划服务、持仓评分服务、行为评分服务
- 数据层：MySQL + Redis 缓存
- Job 调度：APScheduler（已集成）

---

## 3. 数据模型（新增/扩展）

### 3.1 新增：交易计划表 `trading_plan`

#### 表结构（建议 MySQL）

```sql
CREATE TABLE trading_plan (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  account_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  entry_price DECIMAL(20, 6) NOT NULL,
  stop_loss DECIMAL(20, 6) NOT NULL,
  take_profit DECIMAL(20, 6) NOT NULL,
  target_position DECIMAL(10, 4) NOT NULL,
  plan_status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  plan_tags JSON NULL,
  valid_from DATETIME NULL,
  valid_until DATETIME NULL,
  notes VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_plan_account_status (account_id, plan_status),
  INDEX idx_plan_symbol (symbol),
  INDEX idx_plan_valid_until (valid_until)
);
```

#### 枚举约束

- `plan_status`：`ACTIVE` / `EXECUTED` / `EXPIRED` / `CANCELLED`

#### 业务约束

- `entry_price > 0`
- `stop_loss > 0` 且 `stop_loss < entry_price`
- `take_profit > entry_price`
- `0 < target_position <= 1`

### 3.2 扩展：持仓评估响应

在 `PositionsAssessmentResponse.positions[*]` 中增加：

- `budget_utilization`：风险预算占用率（0~1）
- `plan_deviation`：计划偏离度（0~100）

计算建议：

- `budget_utilization = current_risk / risk_budget`
- `plan_deviation = clamp(|current_price - entry_price| / entry_price * 100, 0, 100)`

### 3.3 扩展：行为评分

在 `AiStateView.symbols[*]` 中增加：

- `discipline_score`（0~100）

规则：

- 过度交易 + 偏离计划 ⇒ `discipline_score` 降低

---

## 4. API 设计（可直接编码）

### 4.1 计划模块（新增）

#### 路由

- `GET /api/v1/plan/list`
- `POST /api/v1/plan/create`
- `PATCH /api/v1/plan/{id}`
- `DELETE /api/v1/plan/{id}`

#### Schema（Pydantic）

```python
class PlanView(BaseModel):
    id: int
    account_id: str
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    target_position: float
    plan_status: str
    plan_tags: dict | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

class PlanCreateRequest(BaseModel):
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    target_position: float
    plan_tags: dict | None = None
    valid_until: datetime | None = None
    notes: str | None = None

class PlanUpdateRequest(BaseModel):
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    target_position: float | None = None
    plan_status: str | None = None
    plan_tags: dict | None = None
    valid_until: datetime | None = None
    notes: str | None = None

class PlanListResponse(BaseModel):
    status: str
    total: int
    plans: list[PlanView]
```

#### 示例响应

```json
{
  "status": "ok",
  "total": 1,
  "plans": [
    {
      "id": 12,
      "account_id": "U123456",
      "symbol": "AAPL",
      "entry_price": 182.5,
      "stop_loss": 175.0,
      "take_profit": 198.0,
      "target_position": 0.2,
      "plan_status": "ACTIVE",
      "plan_tags": {"strategy": "trend"},
      "valid_from": "2026-01-15T00:00:00Z",
      "valid_until": "2026-01-20T00:00:00Z",
      "notes": "等待回踩确认",
      "created_at": "2026-01-16T09:00:00Z",
      "updated_at": "2026-01-16T09:00:00Z"
    }
  ]
}
```

### 4.2 计划匹配（扩展机会扫描）

对 `OpportunityRunView.items[*]` 扩展：

- `plan_match_score: float`（0~1）
- `plan_match_reason: str`

### 4.3 监控健康（精简字段）

`GET /api/v1/monitoring/health` 增加：

- `last_updated: datetime`

---

## 5. 服务与路由实现（可直接编码）

### 5.1 Router 结构

新增 `app/routers/trading_plan.py`，并在 `app/main.py` 中注册：

```python
from app.routers import trading_plan
app.include_router(trading_plan.router, prefix="/api/v1", tags=["交易计划"])
```

### 5.2 TradingPlanService（核心逻辑）

#### 核心流程

- `create_plan`：校验价格区间 → 写入 DB → 返回 PlanView
- `list_plans`：按 `account_id` + `status` + `symbol` 过滤
- `update_plan`：部分字段更新，若 `plan_status` = `EXECUTED` 写入执行时间
- `delete_plan`：软删建议（可选）

#### 伪代码

```text
def create_plan(account_id, payload):
  validate(payload)
  plan = TradingPlan(**payload, account_id=account_id)
  session.add(plan)
  session.commit()
  return plan
```

### 5.3 PositionScoringService（扩展）

#### 新增字段来源

- `budget_utilization`：由 risk budget（可从 settings 或 DB 风险配置）
- `plan_deviation`：通过 `trading_plan` 与当前价比对

#### 计算伪代码

```text
budget_utilization = current_risk / max(risk_budget, 1e-6)
plan_deviation = min(abs(price - entry_price) / entry_price * 100, 100)
```

### 5.4 BehaviorScoringService（扩展）

#### 规则

- 若 `overtrade_score > 70` 且 `plan_deviation > 30` ⇒ `discipline_score` 降低 15~30 分

---

## 6. Schema 与模型落地清单

新增文件：

- `app/models/trading_plan.py`
- `app/schemas/trading_plan.py`
- `app/services/trading_plan_service.py`
- `app/routers/trading_plan.py`

扩展文件：

- `app/schemas/position_assessment.py`
- `app/schemas/ai_state.py`
- `app/schemas/opportunities.py`
- `app/routers/position_macro.py`
- `app/routers/opportunities.py`
- `app/routers/api_monitoring.py`
- `app/services/ai_advice_service.py`

---

## 7. 任务调度

新增任务：

- `plan_expiration_job`：每日标记过期计划

伪代码：

```text
UPDATE trading_plan
SET plan_status = 'EXPIRED'
WHERE plan_status = 'ACTIVE'
  AND valid_until < NOW();
```

---

## 8. 缓存策略

- `positions/assessment`：30s TTL
- `plan/list`：10s TTL（可选）
- `macro/risk/overview`：120s TTL

缓存 Key 建议：

- `plan:list:{account_id}:{status}:{symbol}`

---

## 9. 错误处理与降级

- 若 `plan` 模块未上线：前端隐藏计划相关模块
- 新字段缺失：前端显示 `N/A` 并不阻塞主流程

---

## 10. 测试建议

- API 单测：计划 CRUD
- 集成测试：`positions/assessment` 含新字段
- 任务调度测试：过期计划自动标记

---

## 11. 交付清单

- 路由与 Service 实现
- DB Migration（Alembic）
- Schema 更新
- 文档同步更新
