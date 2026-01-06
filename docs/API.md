# API 文档（以 FastAPI 实现为准）

> 说明：本项目目前同时存在“根级端点”和“/api/v1 前缀端点”。
>
> - 根级：health / ai / admin / run-auto-hedge-once
> - `/api/v1`：positions / macro / opportunities

Base URL 以你的启动参数为准（示例：`http://localhost:8088`）。

## Health（根级）

### GET /health

- 用途：服务健康检查
- 响应关键字段：`{ status, mode }`

## AI（根级）

### GET /ai/state

- 用途：返回当前风控状态 + Greeks 敞口 + 行为画像
- Query：`window_days?: int`
- 响应关键字段：
  - `trade_mode`
  - `limits{...}`
  - `exposure{...}`
  - `symbols{ [symbol]: { behavior_score, sell_fly_score, ... } }`

### POST /ai/advice

- 用途：AI 决策助手（结构化建议 + 订单草案）
- 请求：`AiAdviceRequest`
- 响应：`AiAdviceResponse`

## Admin（根级）

### POST /admin/behavior/rebuild

- 用途：重算最近 N 天行为评分
- 请求：`{ account_id?: string, window_days?: int }`
- 响应关键字段：`{ status, account_id, window_days, symbols_processed, metrics }`

### Scheduler

- GET `/admin/scheduler/jobs`
- POST `/admin/scheduler/jobs/{job_id}/pause`
- POST `/admin/scheduler/jobs/{job_id}/resume`
- PUT `/admin/scheduler/jobs/{job_id}/schedule`

详见：[Operations/Scheduler](./Operations/Scheduler.md)

## Positions（/api/v1）

### GET /api/v1/positions/assessment

- 用途：获取所有持仓的综合评估
- Query：`window_days?: int`（当前实现接受该参数，但评估窗口主要由服务内部决定）
- 响应关键字段：
  - `positions[]`：每项包含 `symbol/quantity/avg_cost/current_price/...`
  - **新增：`trend_snapshot`**（日线走势快照：趋势/量比/关键价位/AI 摘要等）
  - `summary{ total_positions, total_value, total_pnl, avg_score, ... }`

### GET /api/v1/positions/{symbol}/technical

- 用途：获取技术分析
- Query：`timeframe`（默认 `1D`），`force_refresh`（默认 false）
- 响应关键字段：`trend_direction, trend_strength, rsi, macd, bollinger_upper/lower, support[], resistance[], volume_ratio, ai_summary, timestamp`

### GET /api/v1/positions/{symbol}/fundamental

- 用途：获取基本面分析
- Query：`force_refresh`（默认 false）
- 响应关键字段：`valuation/profitability/growth/health/overall_score/ai_summary/timestamp`

### POST /api/v1/positions/refresh

- 用途：刷新持仓评估（技术/基本面/综合评分），并写入日线趋势快照缓存
- Body：`symbols?: string[]`（不传则刷新全部持仓）
- Query：`force?: bool`
- 响应关键字段：`{ refreshed: string[], results: { technical, fundamental, scores } }`

## Macro（/api/v1）

### GET /api/v1/macro/risk/overview

- 用途：宏观风险概览（带缓存与 AI 解读）
- Query：`force_refresh?: bool`
- 响应关键字段：
  - `timestamp`
  - `overall_risk{ score, level, summary, confidence }`
  - `risk_breakdown{ monetary_policy, geopolitical, sector_bubble, economic_cycle, market_sentiment }`
  - `alerts[]`
  - `key_concerns[]`
  - `recommendations[]`
  - `ai_analysis`（可能为 AI 生成或默认摘要）
  - `recent_events[]`
  - `_meta{ response_time_ms, cache_hit, data_freshness }`

### GET /api/v1/macro/monetary-policy

- 用途：货币政策与经济周期分析
- 响应关键字段：`{ monetary_policy, economic_cycle, last_updated }`

### GET /api/v1/macro/geopolitical-events

- Query：`days`（默认 30）、`category?`、`min_impact`
- 响应关键字段：`{ total_events, risk_assessment, events[] }`

### POST /api/v1/macro/refresh

- Query：`refresh_indicators` / `refresh_events` / `refresh_risk`
- 响应关键字段：`{ message, timestamp, results }`

## Opportunities（/api/v1）

### GET /api/v1/opportunities/latest

- Query：`universe_name`（默认 `US_LARGE_MID_TECH`）
- 响应关键字段：`{ status, latest }`

### GET /api/v1/opportunities/runs

- Query：`limit`（默认 20）、`universe_name?`
- 响应关键字段：`{ status, runs[] }`

### GET /api/v1/opportunities/runs/{run_id}

- 响应：单次 run 详情（含 items）

### POST /api/v1/opportunities/scan

- 用途：触发扫描并落库；可选更新定时任务 cron
- 请求关键字段：`universe_name/min_score/max_results/force_refresh/schedule_cron?/schedule_timezone?`
- 响应关键字段：`{ status, run, notes? }`
