# 前端对接文档（FastAPI /api/v1）

> 文档版本：v1.0
> 日期：2026-01-16

---

## 1. 基础信息

- Base URL：按部署环境配置（示例：`http://localhost:8088`）
- 健康检查：`GET /health`
- 业务接口统一前缀：`/api/v1`
- Content-Type：`application/json`

---

## 2. 通用约定

### 2.1 响应结构

- 成功响应通常包含 `status` 字段（如 `ok` / `success`）。
- 错误响应遵循 FastAPI 标准：
  - HTTP 400/404/500
  - Body：`{ "detail": "错误说明" }`

### 2.2 缓存与刷新

部分接口启用短 TTL 缓存（如 `ai/state`、`positions/assessment`、`macro/risk/overview`）。
如需强制刷新，请使用 `force_refresh=true` 查询参数（若接口支持）。

---

## 3. 关键接口清单（前端主流程）

### 3.1 AI 状态（仪表盘核心）

- `GET /api/v1/ai/state`
- Query：`window_days?`, `force_refresh?`
- 重点字段：
  - `trade_mode`
  - `limits` / `exposure`
  - `symbols.{symbol}.discipline_score`

### 3.2 持仓评估

- `GET /api/v1/positions/assessment`
- Query：`window_days?`, `force_refresh?`
- 重点字段：
  - `positions[].trend_snapshot`
  - `positions[].budget_utilization`
  - `positions[].plan_deviation`

### 3.3 交易计划

- `GET /api/v1/plan/list`（查询）
- `POST /api/v1/plan/create`（创建）
- `PATCH /api/v1/plan/{id}`（更新）
- `DELETE /api/v1/plan/{id}`（删除）

前端建议：

- 列表页支持 `status` / `symbol` 过滤。
- 计划状态建议映射为：ACTIVE / EXECUTED / EXPIRED / CANCELLED。

### 3.4 执行列表（机会扫描）

- `GET /api/v1/opportunities/latest`
- `POST /api/v1/opportunities/scan`（异步）

说明：

- 扫描接口会先返回 `status=SCHEDULED`，需轮询：
  - `GET /api/v1/opportunities/runs` 或 `GET /api/v1/opportunities/runs/{run_id}`
- 列表项可能包含计划匹配：
  - `plan_match_score` / `plan_match_reason`

### 3.5 宏观风险（降级版）

- `GET /api/v1/macro/risk/overview`
- 建议展示：`overall_risk.score/level/summary`

### 3.6 系统健康

- `GET /api/v1/monitoring/health`
- 重点字段：`status`, `last_updated`

---

## 4. 常见前端接入建议

### 4.1 轮询与去抖

- 高频接口建议 30–60s 轮询。
- 手动刷新按钮需加入 debounce（300–500ms）。

### 4.2 异步任务处理

机会扫描属于异步任务：

- 成功触发后显示“执行中”状态。
- 3–5 秒轮询一次，直到 `status=SUCCESS/FAILED`。

### 4.3 异常提示

- 统一处理 `detail` 字段。
- 关键页（仪表盘/持仓评估）支持“重试”按钮。

---

## 5. 对接验收清单

- 接口路径均为 `/api/v1/*`（`/health` 例外）
- 交易计划 CRUD 能正常工作
- 持仓评估包含 `budget_utilization` 与 `plan_deviation`
- 机会扫描能够异步获取最终结果
- 系统健康包含 `last_updated`

---

如需我补充接口示例请求/响应或前端类型定义（TypeScript），直接告诉我。
