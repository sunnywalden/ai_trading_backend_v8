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
- 策略管理（/api/v1）
- 持仓评估（/api/v1）
- 宏观风险（/api/v1）
- 潜在机会（/api/v1）
- 管理接口（/api/v1）
- 交易计划（/api/v1）
- **API 监控与 Rate Limit 管理**（/api/v1）
- 市场体制感知（/api/v1/regime）— V10.2-M1
- 事件日历 & 围栏管理（/api/v1/events）— V10.2-M2
- 动态仓位生命周期（/api/v1/positions）— V10.2-M3
- 信号融合（/api/v1/signals）— V10.2-M4
- 交易归因（/api/v1/attribution）— V10.2-M5
- AI 洞察 & 进化（/api/v1/insights）— V10.2-M6
- Trading Copilot（/api/v1/copilot）— V10 & V10.2-M7

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
  - `recommendations`（后端统一增强后通常为 `string[]`；兼容历史数据时可能是 `string`）
  - `ai_analysis`（可能为 AI 生成或默认摘要）
  - `market_calibration{ enabled, window, penalty, regime, factors{ vix_change_pct, oil_change_pct, dxy_change_pct }, drivers[] }`
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

### System Monitor 增强端点（V10.4.3 追加需求）

用于 `/system` 页的生命周期、数据流和服务拓扑统一监控。

#### GET `/api/v1/system-monitor/lifecycle`

- 用途：获取交易生命周期总览
- Query：`window_minutes?: int = 60`, `only_exceptions?: bool = false`, `stage_id?: int`, `symbol?: str`
- 响应：`LifecycleOverviewResponse`
- 响应关键字段：
  - `meta{ generated_at, window_minutes, refresh_interval_seconds }`
  - `headline{ active_intents, stuck_intents, exception_count, p95_stage_seconds }`
  - `pipeline[]`：每个阶段的 `active_count/stuck_count/warn_count/critical_count/avg_seconds/p50_seconds/p95_seconds`
  - `plan_fsm[]` / `position_fsm[]`
  - `exceptions[]`：异常 intent 摘要

#### GET `/api/v1/system-monitor/lifecycle/{intent_id}`

- 用途：获取单个 execution intent 的生命周期明细
- 响应：`LifecycleIntentDetailResponse`
- 响应关键字段：
  - `intent_id`, `idempotency_key`, `plan_id`, `symbol`, `action`, `signal_type`
  - `current_stage_id/current_stage_key/current_stage_label`
  - `plan_fsm_state`, `position_fsm_state`
  - `timeline[]`：阶段轨迹与状态转换事件
  - `latest_errors[]`

#### GET `/api/v1/system-monitor/data-flows`

- 用途：获取关键数据流链路总览
- Query：`window_minutes?: int = 60`, `include_healthy?: bool = true`
- 响应：`DataFlowOverviewResponse`
- 响应关键字段：
  - `flows[]`
  - `flows[].nodes[]`：每个节点的 `heartbeat_at/last_success_at/lag_seconds/queue_depth/error_count_24h/degraded`

#### GET `/api/v1/system-monitor/data-flows/{flow_name}`

- 用途：获取单条数据流的节点详情与失败样本
- Query：`window_minutes?: int = 60`, `limit_failures?: int = 20`
- 响应：`DataFlowDetailResponse`
- 响应关键字段：`nodes[]`, `failures[]`

#### GET `/api/v1/system-monitor/services`

- 用途：获取模块树与细粒度服务状态总览
- Query：`window_minutes?: int = 60`, `module?: str`, `status?: str`, `degraded_only?: bool = false`
- 响应：`ServiceOverviewResponse`
- 响应关键字段：
  - `modules[]`：模块级聚合状态
  - `services[]`：服务级明细，字段含 `service_kind/status/latency_ms/error_count_24h/last_recovered_at/dependencies[]`

#### GET `/api/v1/system-monitor/services/{service_name}`

- 用途：获取单服务健康时间线与最近失败样本
- Query：`window_minutes?: int = 60`, `limit_failures?: int = 20`
- 响应：`ServiceDetailResponse`

#### DTO 约束（定稿）

- 所有状态枚举统一为：`HEALTHY | WARN | CRITICAL | UNKNOWN`
- 所有时间戳统一返回 ISO8601 UTC 字符串
- `lag_seconds`, `queue_depth`, `latency_ms` 等不适用时返回 `null`
- 不返回格式化百分比字符串，全部返回数值型原始字段

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

## 市场体制感知（/api/v1/regime）— V10.2-M1

### GET /api/v1/regime/current
- 用途：查询当前体制及置信度
- 响应关键字段：`{ regime, confidence, detected_at, multipliers }`

### GET /api/v1/regime/history
- 用途：历史体制记录（分页）
- Query：`limit?`, `offset?`
- 响应：`{ total, items[] }`

### GET /api/v1/regime/strategy-weights
- 用途：当前体制下各策略权重
- 响应：`{ regime, weights: {strategy_id: weight} }`

### POST /api/v1/regime/override
- 用途：人工覆写当前体制（管理员）
- 请求：`{ regime: str, reason: str }`
- 响应：`{ ok, applied_regime }`

---

## 事件日历 & 围栏管理（/api/v1/events）— V10.2-M2

### GET /api/v1/events/calendar
- 用途：获取事件日历列表（盈利/FOMC/CPI/NFP 等）
- Query：`lookahead_days?: int`（默认 14）, `symbol?: str`
- 响应：`EventCalendarItemResponse[]`，每项包含 `event_id/symbol/event_type/event_date/risk_level/fence_active/eps_estimate/eps_actual/reaction_pct`

### GET /api/v1/events/earnings-fence
- 用途：获取所有当前激活的盈利围栏状态列表
- 响应：`FenceStatusResponse[]`，每项包含 `symbol/event_id/fence_active/days_to_event/size_cap_pct`

### GET /api/v1/events/earnings-fence/{symbol}
- 用途：查询指定标的盈利围栏状态
- 响应：`FenceStatusResponse`

### PUT /api/v1/events/earnings-fence/{event_id}/override
- 用途：人工覆盖围栏（解除或强制激活）
- 请求：`{ active: bool, reason: str }`
- 响应：更新后的 `EventCalendarItemResponse`

### POST /api/v1/events/earnings-result
- 用途：录入盈利实际结果（EPS 实际值、营收、反应涨跌幅）
- 请求：`{ event_id: int, eps_actual: float, revenue_actual?: float, reaction_pct: float }`
- 响应：更新后的 `EventCalendarItemResponse`

---

## 动态仓位生命周期（/api/v1/positions）— V10.2-M3

### POST /api/v1/positions/{position_id}/lifecycle
- 用途：对持仓执行生命周期决策（检查加仓/减仓/移动止损条件）
- 请求：`PositionContext`（包含 `account_id/symbol/current_price/entry_price/quantity/stop_loss/take_profit/market_regime`）
- 响应：`LifecycleStatusResponse`（包含 `action/scale_direction/new_stop_loss/reason/triggered_rules[]`）

### POST /api/v1/positions/{position_id}/manual-scale
- 用途：手动触发仓位缩放（加仓或减仓）
- 请求：`ManualScaleRequest`（`scale_type: SCALE_IN/SCALE_OUT`, `qty_pct: float`, `reason?: str`）
- 响应：更新后的持仓状态

### POST /api/v1/positions/scale-in-candidates
- 用途：扫描所有持仓，返回符合加仓条件的候选列表
- 请求：`{ account_id: str }`
- 响应：`ScaleInCandidatesResponse`（`candidates[]` 含 `symbol/score/suggested_qty_pct/reason`）

---

## 信号融合（/api/v1/signals）— V10.2-M4

### POST /api/v1/signals/fuse
- 用途：将多维原始信号融合为统一置信度评分
- 请求：`FusedSignalRequest`（`symbol/tech_score/fundamental_score/macro_score/volatility_score/options_score/sentiment_score/market_regime?`）
- 响应：`FusedSignalResponse`（`composite_score/weights_used/dim_scores{tech/fundamental/macro/volatility/options/sentiment}/regime_multiplier/signal_strength`）

### POST /api/v1/signals/sentiment/{symbol}
- 用途：获取指定标的的实时情绪评分（新闻 + 社交媒体）
- 响应：`SentimentScoreResponse`（`symbol/sentiment_score/bearish_pct/bullish_pct/neutral_pct/source_count/analyzed_at`）

---

## 交易归因（/api/v1/attribution）— V10.2-M5

### GET /api/v1/attribution/trades
- 用途：获取交易三层归因分析列表
- Query：`days?: int`（默认 30）, `symbol?: str`, `category?: str`（alpha_source/execution/position_mgmt）
- 响应：`TradeAttributionItemResponse[]`，每项包含 `trade_id/symbol/realized_pnl/alpha_pnl/exec_pnl/pos_mgmt_pnl/alpha_source/exec_quality_score/layers{}`

### GET /api/v1/attribution/summary
- 用途：获取归因汇总统计（三层 PnL 占比 + 最佳/最差策略）
- Query：`days?: int`（默认 30）
- 响应：`AttributionSummaryResponse`（`total_pnl/alpha_contribution_pct/exec_contribution_pct/pos_mgmt_contribution_pct/top_alpha_sources[]/exec_quality_avg/by_category{}`）

---

## AI 洞察 & 进化（/api/v1/insights）— V10.2-M6

### GET /api/v1/insights/repository
- 用途：获取 AI 洞察知识库列表
- Query：`insight_type?: str`（WEEKLY_SUMMARY/PATTERN/LESSON/RULE_CANDIDATE）, `active?: bool`
- 响应：`InsightListResponse`（`total/items[]`，每项含 `insight_id/insight_type/title/body/confidence/active/source_trades/created_at`）

### POST /api/v1/insights/repository
- 用途：手动添加洞察条目
- 请求：`AIInsightItemCreate`（`insight_type/title/body/confidence/source_trades?`）
- 响应：`AIInsightItemResponse`

### PATCH /api/v1/insights/repository/{insight_id}
- 用途：更新洞察状态（激活/停用）或内容
- 请求：`{ active?: bool, body?: str, confidence?: float }`
- 响应：更新后的 `AIInsightItemResponse`

### GET /api/v1/insights/experiments
- 用途：获取 A/B 实验列表
- Query：`status?: str`（RUNNING/COMPLETED/PAUSED）
- 响应：`ABExperimentItemResponse[]`

### POST /api/v1/insights/experiments
- 用途：创建新 A/B 实验
- 请求：`CreateExperimentRequest`（`name/description/hypothesis/control_params/test_params/target_metric/start_date/end_date`）
- 响应：`ABExperimentItemResponse`（含 `experiment_id/status/statistical_significance/p_value`）

---

## Trading Copilot（/api/v1/copilot）— V10 & V10.2-M7

### POST /api/v1/copilot/chat
- 用途：发送 Copilot 对话消息
- 请求：`{ account_id, session_id, message }`
- 响应：`{ reply, action_intent?, tokens_used, model_used }`

### GET /api/v1/copilot/history
- 用途：获取会话历史
- Query：`account_id`, `session_id`, `limit?`

### DELETE /api/v1/copilot/history
- 用途：清空会话历史

### POST /api/v1/copilot/confirm/{action_id}
- 用途：确认 Copilot 意图操作
- 响应：`{ executed, result }`

### GET /api/v1/copilot/morning-brief
- 用途：盘前摘要（每日 08:30 ET）

### GET /api/v1/copilot/daily-report
- 用途：当日复盘报告

### POST /api/v1/copilot/deep-research — V10.2-M7
- 用途：对指定标的执行多步深度研究，返回结构化研究报告
- 请求：`{ symbol: str, query?: str }`
- 响应：`{ report: DeepResearchReport }`
  - `DeepResearchReport` 字段：`symbol/rating/price_target/body/sources[]/model_used/generated_at`
- 说明：内部调用 `deepseek-reasoner` 分多步执行：市场情绪分析 → 基本面深潜 → 风险因素扫描 → 综合评级

---

## 更新历史

- **2026-02-28**: V10.2-M2~M8 上线；新增事件日历、动态仓位、信号融合、交易归因、AI 洞察进化、Copilot Deep Research 共 18 个端点；文档补全
- **2026-02-27**: V10.2-M1 上线；新增 `/api/v1/regime` 4 个端点
- **2026-01-16**: 统一所有接口路径为 `/api/v1` 前缀（除 `/health` 外）；更新文档所有接口路径
- **2026-01-09**: 合并 `API_Monitoring.md`（API 监控模块）到主文档；补充监控端点与操作说明
- 其它历史记录请见各相关文件头部注释

---

## 相关文档

- [Configuration.md](Configuration.md) - 系统配置说明
- [Operations/Scheduler.md](Operations/Scheduler.md) - 调度器与运维

---

*此处展示了合并后的集中文档：API 使用说明与监控指南均在本文件中。若需对监控进行更详细的设计说明，请参见项目内服务实现 `app/services/api_monitoring_service.py`。*
