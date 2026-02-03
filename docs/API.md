# API 文档（以 FastAPI 实现为准）

> 说明：本项目已统一接口路径规范（2026-01-16更新）：
>
> - **健康检查**：`/health`（无前缀）
> - **所有业务接口**：`/api/v1/*`（统一前缀）
>
> 注意：本文档已包含“API 监控（Rate Limit）”部分，原文件 `docs/API_Monitoring.md` 已合并（并标记为已合并/弃用）。

Base URL 以你的启动参数为准（示例：`http://localhost:8088`）。

---

## 目录

- Health（系统接口）
- AI 决策（/api/v1）
- 持仓评估（/api/v1）
- 宏观风险（/api/v1）
- 潜在机会（/api/v1）
- 管理接口（/api/v1）
- 交易计划（/api/v1）
- **API 监控与 Rate Limit 管理**（/api/v1）

---

## Health（系统接口）

### GET /health

- 用途：服务健康检查
- 响应关键字段：`{ status, mode }`

## AI 决策（/api/v1）

### GET /api/v1/ai/state

- 用途：返回当前风控状态 + Greeks 敞口 + 行为画像
- Query：`window_days?: int`
- 响应关键字段：
  - `trade_mode`
  - `limits{...}`
  - `exposure{...}`
  - `symbols{ [symbol]: { behavior_score, sell_fly_score, discipline_score, ... } }`

### POST /api/v1/ai/advice

- 用途：AI 决策助手（结构化建议 + 订单草案）
- 请求：`AiAdviceRequest`
- 响应：`AiAdviceResponse`

## 策略管理（/api/v1）

### GET /api/v1/strategies

- 用途：列出可用策略，支持筛选、搜索与分页。
- Query：`style?`, `is_builtin?`, `limit?`（默认 20）、`offset?`（默认 0）、`search?`
- 响应核心字段：`{ status, strategies[] }`，每个策略包括 `id/name/style/is_builtin/is_active/tags/last_run_status/last_run_at`。

### GET /api/v1/strategies/{strategy_id}

- 用途：获取单个策略的完整定义。
- 响应：`{ strategy: { id/name/style/description/tags/default_params/signal_sources/risk_profile/is_active/is_builtin/version } }`。

### POST /api/v1/strategies

- 用途：创建策略（需要策略管理权限，见 `settings.STRATEGY_MANAGE_USERS`）。
- 请求：`StrategyCreateRequest`（`name/style/description/default_params/signal_sources/risk_profile/tags/is_builtin/is_active`）。
- 响应：`StrategyDetailResponse`。

### PATCH /api/v1/strategies/{strategy_id}/params

- 用途：更新策略的默认参数（需要管理权限）。
- 请求：`{ default_params: {...} }`。
- 响应：更新后的策略摘要 plus 版本与参数。

### POST /api/v1/strategies/{strategy_id}/run

- 用途：按需触发策略执行，支持单次调度与异步运行。
- 请求：`StrategyRunRequest`，字段包括 `account_id`, `budget?`, `direction?`, `param_overrides?`, `notify_channels?`, `target_universe?`, `priority?`。
- 系统会根据 `settings.ENABLE_SCHEDULER`，将任务交由调度器 `add_job(...)`（延迟 ~2s） 或直接 `asyncio.create_task` 执行。
- 响应：`{ run_id, celery_task_id }`（`celery_task_id` 也是调度 job id）。

### GET /api/v1/strategy-runs/{run_id}/status

- 用途：查询某次运行的状态、进度与时间线。
- 响应：`{ run_id, status, phase, progress, attempt, error_message?, started_at?, finished_at?, timeline? }`。

### GET /api/v1/strategy-runs/latest

- 用途：返回某个账号/策略最新一条运行记录（可选 `account_id`, `strategy_id`）。
- 响应：`{ run?: { ...status view... } }`，`run` 可能为 `null`。

### GET /api/v1/strategy-runs

- 用途：分页获得历史运行（可筛选 `strategy_id`, `account_id`, `status`）。
- 响应：`runs[]`，每项：`run_id/strategy_id/status/started_at/finished_at/hits/hit_rate/avg_signal_strength`。

### GET /api/v1/strategy-runs/{run_id}/results

- 用途：获取某次运行的资产与信号详情。
- 响应：`{ run_id, strategy_id, assets[] }`，每个资产包含 `symbol/signal_strength/weight/risk_flags/notes/signal_dimensions`。

### POST /api/v1/strategy-runs/{run_id}/export

- 用途：将指定运行的资产导出为 CSV 并返回下载链接。
- 响应：`{ run_id, download_url, file_path }`，其中 `download_url` 指向 `/exports/strategy_runs/strategy_run_{run_id}.csv`。

## 管理接口（/api/v1）

### POST /api/v1/admin/behavior/rebuild

- 用途：重算最近 N 天行为评分
- 请求：`{ account_id?: string, window_days?: int }`
- Query：`async_run?: bool`（是否异步执行，返回调度任务ID）
- 响应关键字段：`{ status, account_id, window_days, symbols_processed, metrics }`

### POST /api/v1/run-auto-hedge-once

- 用途：手动触发自动对冲执行
- 响应关键字段：`{ status, detail }`

### Scheduler

- GET `/api/v1/admin/scheduler/jobs`
- POST `/api/v1/admin/scheduler/jobs/{job_id}/pause`
- POST `/api/v1/admin/scheduler/jobs/{job_id}/resume`
- PUT `/api/v1/admin/scheduler/jobs/{job_id}/schedule`

详见：[Operations/Scheduler](./Operations/Scheduler.md)

## 交易计划（/api/v1）

### GET /api/v1/plan/list

- 用途：查询交易计划列表
- Query：`status?` / `symbol?`

### POST /api/v1/plan/create

- 用途：创建交易计划
- 请求：`PlanCreateRequest`

### PATCH /api/v1/plan/{id}

- 用途：更新交易计划
- 请求：`PlanUpdateRequest`

### DELETE /api/v1/plan/{id}

- 用途：删除交易计划

## 持仓评估（/api/v1）

### GET /api/v1/positions/assessment

- 用途：获取所有持仓的综合评估
- Query：
  - `window_days?: int`（当前实现接受该参数，但评估窗口主要由服务内部决定）
  - `force_refresh?: bool`（是否强制刷新缓存与快照）
- 响应关键字段：
  - `positions[]`：每项包含 `symbol/quantity/avg_cost/current_price/...`
  - **新增：`trend_snapshot`**（日线走势快照：趋势/量比/关键价位/AI 摘要等）
  - **新增：`budget_utilization`**（风险预算占用率 0~1）
  - **新增：`plan_deviation`**（计划偏离度 0~100）
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
- Query：
  - `force?: bool`
  - `async_run?: bool`（是否异步执行，返回调度任务ID）
- 响应关键字段：`{ refreshed: string[], results: { technical, fundamental, scores } }`

## 宏观风险（/api/v1）

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

## 潜在机会（/api/v1）

### GET /api/v1/opportunities/latest

- Query：`universe_name`（默认 `US_LARGE_MID_TECH`）
- 响应关键字段：`{ status, latest }`
- 响应关键字段：`{ status, latest }`，其中 `latest.items[*]` 可能包含 `plan_match_score` / `plan_match_reason`

### GET /api/v1/opportunities/runs

- Query：`limit`（默认 20）、`universe_name?`
- 响应关键字段：`{ status, runs[] }`

### GET /api/v1/opportunities/runs/{run_id}

- 响应：单次 run 详情（含 items）

### POST /api/v1/opportunities/scan

- 用途：触发扫描并落库（**异步返回**）。请求会立即返回一个带 `status=SCHEDULED` 的占位 run，并在后台异步执行扫描任务，实际扫描完成后会写入或替换最终的 run 记录。
- 请求关键字段：`universe_name/min_score/max_results/force_refresh/schedule_cron?/schedule_timezone?`
- 响应关键字段：
  - `{ status, run, notes? }`：其中 `run.status` 在接口返回时可能为 `SCHEDULED`（占位），`notes` 会包含 `scheduled_job_id` 和 `scheduled_run_id`，可用于后续查询和追踪。  
  - 建议客户端在收到响应后轮询 `GET /api/v1/opportunities/runs` 或 `GET /api/v1/opportunities/runs/{run_id}` 来获取最终结果（`status=SUCCESS` 或 `FAILED`）。

---

## API 监控与 Rate Limit 管理（新）

为确保系统稳定运行并遵守各外部API的使用限制，系统实现了完整的 API 调用监控与 Rate Limit 管理模块。

### 概述

系统自动跟踪并记录外部 API 的调用（按日/小时/分钟），包括成功率、错误、响应时间与端点级统计；并基于策略计算配额使用率，触发智能告警。

### 覆盖的外部 API

- FRED（宏观经济指标）
- NewsAPI（地缘政治新闻）
- Tiger（行情数据）
- Yahoo Finance（备用行情）
- OpenAI（AI 决策助手）

### 监控指标

- 调用次数（日/小时/分钟）
- 成功/失败次数（错误详情）
- 平均/分位响应时间（ms）
- 端点级统计与错误样本

### Rate Limit 策略（截至 2026-01-09）

| API | 日限制 | 小时限制 | 分钟限制 | 备注 |
|-----|--------:|---------:|---------:|------|
| FRED | 120,000 | - | - | 建议控制在合理范围 |
| News API | 100 | - | - | 免费版限制 |
| Tiger | - | 3,600 | 60 | 约 1 请求/秒 |
| Yahoo Finance | 2,000 | 100 | 5 | 非官方 API，避免被限 |
| OpenAI | - | - | 3 | 取决于订阅级别 |

### 智能告警

- 警告阈值：达到日配额的 **70%** 则发出警告
- 临界阈值：达到日配额的 **90%** 则标记为临界
- 告警内容包含使用率、剩余次数、建议操作（缓降/降级/重试策略）

### 缓存与采样

- 外部数据通过 Redis 缓存（避免重复、降低调用）：
  - 宏观指标：6–24 小时
  - 地缘政治事件：4–24 小时
  - 市场数据：5 分钟–1 小时
- 监控计数与错误样本也保存在 Redis（短期滚动窗口）

### API 端点（监控）

所有监控接口均使用 `/api/v1` 前缀：

- GET `/api/v1/stats/{provider}?time_range=day` - 获取特定API统计
- GET `/api/v1/stats?time_range=day` - 获取所有API统计
- GET `/api/v1/report` - 生成完整监控报告
- GET `/api/v1/rate-limit/{provider}` - 检查Rate Limit状态
- GET `/api/v1/policies` - 获取所有Rate Limit策略
- GET `/api/v1/policies/{provider}` - 获取特定API策略
- GET `/api/v1/monitoring/health` - 监控服务健康检查
  - 响应关键字段：`{ status, last_updated, ... }`

#### 示例（部分）

获取 NewsAPI 的限制状态：
```
GET /api/v1/rate-limit/NewsAPI
```

返回示例：

```json
{
  "provider": "NewsAPI",
  "can_call": true,
  "status": "warning",
  "usage_percent": 72.0,
  "remaining": 28,
  "reason": "",
  "suggestion": "接近限额 (72.0%)，建议减少调用"
}
```

### 配置（.env）

确保 Redis 已配置并启用：

```env
REDIS_ENABLED=true
REDIS_HOST=192.168.2.233
REDIS_PORT=6379
REDIS_DB=0
```

缓存TTL：

```env
CACHE_TTL_TECHNICAL_HOURS=1
CACHE_TTL_FUNDAMENTAL_HOURS=24
CACHE_TTL_MACRO_HOURS=24
CACHE_TTL_GEOPOLITICAL_HOURS=24
```

### 故障排查要点

- 若监控端点返回 404，检查 `api_monitoring` 路由是否已按 `/api/v1` 正确注册
- 若 Redis 无法连接，检查环境变量与 `REDIS_ENABLED`
- 当监控数据异常偏高时，可在 Redis 中查看计数键并排查上游调用方

### 日志示例

```
[FRED] Using Redis cache for fed_funds_rate
[FRED] Successfully fetched and cached cpi
⚠️  NewsAPI 接近限额：已使用 72.00%，剩余 28 次
🚨 NewsAPI 达到临界阈值：已使用 91.00%，剩余 9 次
```

### 最佳实践

1. 定期查看 `/api/v1/report` 并设自动报警（邮件/Slack）
2. 根据业务峰值调整缓存 TTL，避免短平快重复调用
3. 在关键路径加入本地队列/退避以处理瞬时突发调用
4. 定期更新 Rate Limit 策略文档（供应商可能调整限制）

---

## 更新历史

- **2026-01-16**: 统一所有接口路径为 `/api/v1` 前缀（除 `/health` 外）；更新文档所有接口路径
- **2026-01-09**: 合并 `API_Monitoring.md`（API 监控模块）到主文档；补充监控端点与操作说明
- 其它历史记录请见各相关文件头部注释

---

## 相关文档

- [Configuration.md](Configuration.md) - 系统配置说明
- [Operations/Scheduler.md](Operations/Scheduler.md) - 调度器与运维

---

*此处展示了合并后的集中文档：API 使用说明与监控指南均在本文件中。若需对监控进行更详细的设计说明，请参见项目内服务实现 `app/services/api_monitoring_service.py`。*
