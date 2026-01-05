# AI Trading Backend V8 - API 文档

## 目录
- [概述](#概述)
- [基础信息](#基础信息)
- [认证](#认证)
- [API端点](#api端点)
  - [健康检查](#健康检查)
  - [持仓管理](#持仓管理)
  - [宏观风险分析](#宏观风险分析)
  - [潜在机会](#潜在机会)
  - [AI与行为评分](#ai与行为评分)
  - [系统管理](#系统管理)
- [数据模型](#数据模型)
- [错误处理](#错误处理)

---

## 概述

AI Trading Backend V8 提供了一套完整的量化交易分析API，包括：
- 持仓技术面和基本面分析
- 宏观经济风险评估
- 货币政策和地缘政治分析
- 潜在机会扫描（每日自动扫描股票池，推荐 1-3 只标的）
- AI驱动的智能建议（结构化建议 + 回退策略）

## 基础信息

- **Base URL**: `http://localhost:8088`
- **协议**: HTTP/HTTPS
- **数据格式**: JSON
- **字符编码**: UTF-8
- **时区**:
  - 业务时间字段通常为服务端本地时间
  - 机会扫描 `as_of` 使用 Asia/Shanghai（北京时间）

## 认证

当前版本暂不需要认证（开发环境）。生产环境建议添加 API Key 或 JWT Token。

---

## API端点

### 健康检查

#### GET /health

检查服务健康状态。

**请求示例**:
```bash
curl http://localhost:8088/health
```

**响应示例**:
```json
{
  "status": "ok",
  "mode": "REAL"
}
```

**响应字段**:
- `status` (string): 服务状态，"ok" 表示正常
- `mode` (string): 运行模式，取值与后端 `TRADE_MODE` 一致（OFF/DRY_RUN/REAL）

---

### 持仓管理

#### 1. GET /api/v1/positions/assessment

获取所有持仓的综合评估。

**查询参数**:
- `window_days` (int, optional): 评估窗口天数，默认 7

**请求示例**:
```bash
curl "http://localhost:8088/api/v1/positions/assessment?window_days=7"
```

**响应示例**:
```json
{
  "positions": [
    {
      "symbol": "AAPL",
      "quantity": 100,
      "avg_cost": 150.50,
      "current_price": 245.80,
      "market_value": 24580.0,
      "unrealized_pnl": 9530.00,
      "unrealized_pnl_percent": 63.32,
      "overall_score": 75,
      "technical_score": 76,
      "fundamental_score": 79,
      "sentiment_score": 71,
      "recommendation": "HOLD",
      "risk_level": "MEDIUM",
      "target_position": 0.45,
      "stop_loss": 221.22,
      "take_profit": 295.0
    }
  ],
  "summary": {
    "total_positions": 1,
    "total_value": 24580.00,
    "total_pnl": 9530.00,
    "avg_score": 75.0,
    "high_risk_count": 0,
    "buy_recommendation_count": 0
  }
}
```

**响应字段**:
- `positions[]`: 持仓列表
  - `symbol`: 股票代码
  - `quantity`: 持仓数量
  - `avg_cost`: 平均成本
  - `current_price`: 当前价格
  - `market_value`: 市值
  - `unrealized_pnl`: 未实现盈亏
  - `unrealized_pnl_percent`: 未实现盈亏百分比 (%)
  - `technical_score`: 技术面评分 (0-100)
  - `fundamental_score`: 基本面评分 (0-100)
  - `sentiment_score`: 情绪评分 (0-100)
  - `overall_score`: 综合评分 (0-100)
  - `recommendation`: 操作建议 (STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL)
  - `risk_level`: 风险等级 (LOW/MEDIUM/HIGH/EXTREME)
  - `target_position`: 建议仓位比例 (0-1)
  - `stop_loss`: 建议止损价
  - `take_profit`: 建议止盈价
- `summary`: 汇总信息
  - `total_positions`: 持仓总数
  - `total_value`: 总市值
  - `total_pnl`: 总盈亏
  - `avg_score`: 平均评分
  - `high_risk_count`: 高风险持仓数
  - `buy_recommendation_count`: BUY/STRONG_BUY 数量

---

#### 2. GET /api/v1/positions/{symbol}/technical

获取指定股票的技术分析。

**路径参数**:
- `symbol` (string, required): 股票代码，如 "AAPL"

**查询参数**:
- `timeframe` (string, optional): 时间周期，默认 "1d"，可选 "1h", "1d", "1w"
- `force_refresh` (bool, optional): 是否强制刷新，默认 false

**请求示例**:
```bash
curl "http://localhost:8088/api/v1/positions/AAPL/technical?timeframe=1d"
```

**响应示例**:
```json
{
  "symbol": "AAPL",
  "timeframe": "1d",
  "trend_direction": "BEARISH",
  "trend_strength": 75.0,
  "rsi": 43.84,
  "macd": -0.29,
  "macd_signal": 0.45,
  "bollinger_upper": 280.84,
  "bollinger_lower": 268.79,
  "support": [276.15, 269.56, 266.95],
  "resistance": [288.62, 280.15, 275.43],
  "volume_ratio": 1.15,
  "overall_score": 65.5,
  "ai_summary": "从趋势强度来看，AAPL的股价呈现出强劲的上涨态势...",
  "timestamp": "2026-01-04T17:00:00"
}
```

**响应字段**:
- `trend_direction`: 趋势方向 (BULLISH/BEARISH/SIDEWAYS)
- `trend_strength`: 趋势强度 (0-100)
- `rsi`: RSI指标值 (0-100)
- `macd`: MACD值
- `macd_signal`: MACD信号线
- `bollinger_upper`: 布林带上轨
- `bollinger_lower`: 布林带下轨
- `support[]`: 支撑位列表
- `resistance[]`: 阻力位列表
- `volume_ratio`: 成交量比率
- `overall_score`: 综合技术评分 (0-100)
- `ai_summary`: AI生成的技术分析摘要

---

#### 3. GET /api/v1/positions/{symbol}/fundamental

获取指定股票的基本面分析。

**路径参数**:
- `symbol` (string, required): 股票代码

**查询参数**:
- `force_refresh` (bool, optional): 是否强制刷新，默认 false

**请求示例**:
```bash
curl "http://localhost:8088/api/v1/positions/AAPL/fundamental"
```

**响应示例**:
```json
{
  "symbol": "AAPL",
  "valuation": {
    "pe_ratio": 36.38,
    "pb_ratio": 54.30,
    "peg_ratio": null,
    "score": 18.62
  },
  "profitability": {
    "roe": 171.42,
    "roa": 22.96,
    "profit_margin": 26.92,
    "score": 98.97
  },
  "growth": {
    "revenue_growth": 7.9,
    "earnings_growth": 91.2,
    "score": 77.9
  },
  "health": {
    "current_ratio": 0.893,
    "debt_to_equity": 152.41,
    "score": 23.14
  },
  "overall_score": 54.66,
  "ai_summary": "苹果公司在盈利能力和成长性方面表现出色...",
  "timestamp": "2026-01-04T17:00:00"
}
```

**响应字段**:
- `valuation`: 估值指标
  - `pe_ratio`: 市盈率
  - `pb_ratio`: 市净率
  - `peg_ratio`: PEG比率
  - `score`: 估值评分 (0-100)
- `profitability`: 盈利能力指标
  - `roe`: 净资产收益率 (%)
  - `roa`: 总资产收益率 (%)
  - `profit_margin`: 净利润率 (%)
  - `score`: 盈利能力评分 (0-100)
- `growth`: 成长性指标
  - `revenue_growth`: 营收增长率 (%)
  - `earnings_growth`: 利润增长率 (%)
  - `score`: 成长性评分 (0-100)
- `health`: 财务健康指标
  - `current_ratio`: 流动比率
  - `debt_to_equity`: 负债权益比
  - `score`: 财务健康评分 (0-100)
- `overall_score`: 综合基本面评分 (0-100)
- `ai_summary`: AI生成的基本面分析摘要

---

#### 4. POST /api/v1/positions/refresh

刷新所有持仓的技术和基本面数据。

**请求示例**:
```bash
curl -X POST "http://localhost:8088/api/v1/positions/refresh"
```

**响应示例**:
```json
{
  "status": "success",
  "refreshed_count": 5,
  "failed_symbols": [],
  "message": "Successfully refreshed 5 positions",
  "timestamp": "2026-01-04T17:00:00"
}
```

---

### 宏观风险分析

#### 5. GET /api/v1/macro/risk/overview

获取宏观风险综合评估。

**请求示例**:
```bash
curl "http://localhost:8088/api/v1/macro/risk/overview"
```

**响应示例**:
```json
{
  "timestamp": "2026-01-04T17:00:00",
  "overall_risk": {
    "score": 78,
    "level": "MEDIUM",
    "summary": "宏观环境稳定，存在一定风险因素。主要风险来自行业泡沫维度。",
    "confidence": 0.9
  },
  "risk_breakdown": {
    "monetary_policy": {
      "score": 77,
      "description": "货币政策风险评估"
    },
    "geopolitical": {
      "score": 90,
      "description": "地缘政治风险评估"
    },
    "sector_bubble": {
      "score": 60,
      "description": "行业泡沫风险评估"
    },
    "economic_cycle": {
      "score": 85,
      "description": "经济周期风险评估"
    },
    "market_sentiment": {
      "score": 80,
      "description": "市场情绪风险评估"
    }
  },
  "alerts": [
    {
      "level": "WARNING",
      "dimension": "sector_bubble",
      "message": "科技板块估值偏高，存在泡沫风险",
      "recommendation": "适当降低科技股配置"
    }
  ],
  "key_concerns": ["行业泡沫风险上升", "地缘政治不确定性"],
  "recommendations": "保持均衡配置，适当增加防御性资产",
  "ai_analysis": "当前宏观风险等级：MEDIUM。宏观环境整体向好...",
  "recent_events": []
}
```

**响应字段**:
- `overall_risk`: 总体风险
  - `score`: 风险评分 (0-100，越高越安全)
  - `level`: 风险等级 (LOW/MEDIUM/HIGH/CRITICAL)
  - `summary`: 风险摘要
  - `confidence`: 评估置信度 (0-1)
- `risk_breakdown`: 分维度风险
  - `monetary_policy`: 货币政策风险 (权重30%)
  - `geopolitical`: 地缘政治风险 (权重20%)
  - `sector_bubble`: 行业泡沫风险 (权重20%)
  - `economic_cycle`: 经济周期风险 (权重20%)
  - `market_sentiment`: 市场情绪风险 (权重10%)
- `alerts[]`: 风险警报列表
  - `level`: 警报级别 (INFO/WARNING/CRITICAL)
  - `dimension`: 风险维度
  - `message`: 警报消息
  - `recommendation`: 应对建议
- `key_concerns[]`: 主要关注点
- `recommendations`: 总体建议
- `ai_analysis`: AI生成的宏观分析

---

#### 6. GET /api/v1/macro/monetary-policy

获取货币政策和经济周期分析。

**请求示例**:
```bash
curl "http://localhost:8088/api/v1/macro/monetary-policy"
```

**响应示例**:
```json
{
  "monetary_policy": {
    "fed_funds_rate": 3.64,
    "treasury_10y": 4.18,
    "treasury_2y": 3.47,
    "yield_curve_slope": 0.71,
    "inflation_rate": 1.64,
    "m2_growth": 3.51,
    "policy_stance": "中性 (Neutral)",
    "last_updated": "2026-01-04T17:00:00"
  },
  "economic_cycle": {
    "gdp_growth_rate": 1.07,
    "unemployment_rate": 4.6,
    "industrial_production_growth": 0.69,
    "estimated_pmi": 51.38,
    "consumer_sentiment": 51.0,
    "cycle_phase": "复苏期 (Recovery)",
    "recession_probability": 25.0,
    "last_updated": "2026-01-04T17:00:00"
  },
  "last_updated": "2026-01-04T17:00:00"
}
```

**响应字段**:
- `monetary_policy`: 货币政策指标
  - `fed_funds_rate`: 联邦基金利率 (%)
  - `treasury_10y`: 10年期国债收益率 (%)
  - `treasury_2y`: 2年期国债收益率 (%)
  - `yield_curve_slope`: 收益率曲线斜率
  - `inflation_rate`: 通胀率 (%)
  - `m2_growth`: M2货币供应增长率 (%)
  - `policy_stance`: 政策立场 (宽松/中性/紧缩)
- `economic_cycle`: 经济周期指标
  - `gdp_growth_rate`: GDP增长率 (%)
  - `unemployment_rate`: 失业率 (%)
  - `industrial_production_growth`: 工业生产增长率 (%)
  - `estimated_pmi`: 估计PMI值
  - `consumer_sentiment`: 消费者信心指数
  - `cycle_phase`: 经济周期阶段 (衰退/复苏/繁荣/滞胀)
  - `recession_probability`: 衰退概率 (%)

---

#### 7. GET /api/v1/macro/geopolitical-events

获取地缘政治事件和风险评估。

**查询参数**:
- `days` (int, optional): 查询最近N天的事件，默认 7

**请求示例**:
```bash
curl "http://localhost:8088/api/v1/macro/geopolitical-events?days=7"
```

**响应示例**:
```json
{
  "total_events": 3,
  "risk_assessment": {
    "score": 75.0,
    "event_count": 3,
    "avg_severity": 6.5,
    "avg_market_impact": 7.0,
    "risk_level": "MEDIUM"
  },
  "events": [
    {
      "event_id": 1,
      "title": "中美贸易谈判取得进展",
      "category": "TRADE_WAR",
      "severity": 7,
      "market_impact": 8,
      "affected_regions": ["北美", "亚洲"],
      "affected_sectors": ["科技", "制造业"],
      "published_at": "2026-01-03T10:00:00",
      "source": "Reuters",
      "summary": "中美双方在关税问题上达成初步共识..."
    }
  ]
}
```

**响应字段**:
- `total_events`: 事件总数
- `risk_assessment`: 风险评估
  - `score`: 风险评分 (0-100，越高越安全)
  - `event_count`: 事件数量
  - `avg_severity`: 平均严重程度 (1-10)
  - `avg_market_impact`: 平均市场影响 (1-10)
  - `risk_level`: 风险等级 (LOW/MEDIUM/HIGH)
- `events[]`: 事件列表
  - `event_id`: 事件ID
  - `title`: 事件标题
  - `category`: 事件分类 (MILITARY_CONFLICT/TRADE_WAR/SANCTIONS/POLITICAL_CRISIS/TERRORISM/CYBER_ATTACK/DIPLOMATIC_TENSION)
  - `severity`: 严重程度 (1-10)
  - `market_impact`: 市场影响 (1-10)
  - `affected_regions[]`: 受影响地区
  - `affected_sectors[]`: 受影响行业
  - `published_at`: 发布时间
  - `source`: 信息来源
  - `summary`: 事件摘要

---

#### 8. POST /api/v1/macro/refresh

刷新所有宏观指标和地缘政治事件数据。

**请求示例**:
```bash
curl -X POST "http://localhost:8088/api/v1/macro/refresh"
```

**响应示例**:
```json
{
  "status": "success",
  "refreshed_components": [
    "macro_indicators",
    "geopolitical_events",
    "macro_risk_scores"
  ],
  "message": "Successfully refreshed all macro data",
  "timestamp": "2026-01-04T17:00:00"
}
```

---

### 潜在机会

潜在机会模块提供“每日扫描 + 手动扫描 + 结果回溯”能力。

**核心策略（与当前实现一致）**：
- 股票池：动态生成（从候选集合中按 **市值（中大型）+ 行业（科技/科技相关）**筛选）
- 三维门槛：技术/基本面/情绪评分均 ≥ `min_score`
- 宏观融合：当宏观风险等级为 **HIGH/EXTREME** 时，筛选阈值自动提高到 **80**

#### 9. GET /api/v1/opportunities/latest

获取最新一次成功扫描结果。

**查询参数**:
- `universe_name` (string, optional): 股票池名称，默认 `US_LARGE_MID_TECH`

**请求示例**:
```bash
curl "http://localhost:8088/api/v1/opportunities/latest?universe_name=US_LARGE_MID_TECH"
```

**响应示例**:
```json
{
  "status": "ok",
  "latest": null
}
```

当存在结果时：
```json
{
  "status": "ok",
  "latest": {
    "run_id": 3,
    "run_key": "2026-01-05|US_LARGE_MID_TECH|min75|max3|fr0",
    "status": "SUCCESS",
    "as_of": "2026-01-05T20:30:00.000000+08:00",
    "universe_name": "US_LARGE_MID_TECH",
    "min_score": 75,
    "max_results": 3,
    "force_refresh": false,
    "macro_risk": {
      "overall_score": 69,
      "risk_level": "MEDIUM",
      "risk_summary": "..."
    },
    "total_symbols": 20,
    "qualified_symbols": 1,
    "elapsed_ms": 24993,
    "items": [
      {
        "rank": 1,
        "symbol": "MSFT",
        "current_price": 420.1,
        "technical_score": 82,
        "fundamental_score": 80,
        "sentiment_score": 79,
        "overall_score": 81,
        "recommendation": "BUY",
        "reason": "三维评分均达标：T82/F80/S79；趋势 BULLISH(88%)；RSI 52.1"
      }
    ]
  }
}
```

#### 10. POST /api/v1/opportunities/scan

手动触发一次机会扫描并返回本次 run。

**请求体**:
```json
{
  "universe_name": "US_LARGE_MID_TECH",
  "min_score": 75,
  "max_results": 3,
  "force_refresh": false,
  "schedule_cron": "30 20 * * *",
  "schedule_timezone": "Asia/Shanghai"
}
```

**参数说明**:
- `schedule_cron` (string, optional): Linux crontab 5 段格式：`分钟 小时 日 月 周`。
  - 示例：`"30 20 * * *"` 表示每天 20:30
  - 注意：当前仅支持 5 段（不支持含秒的 6 段）
- 默认值：`"30 20 * * *"`（对应当前调度任务 20:30 首次运行）
- `schedule_timezone` (string, optional): cron 表达式解释时区，默认 `Asia/Shanghai`
- 默认值：`"Asia/Shanghai"`（北京时间）

**效果**:
- 如果传入 `schedule_cron`，服务会将定时任务 `scan_daily_opportunities_tech` 的触发时间更新为对应 cron。
- 本次请求仍会立即执行一次扫描并返回结果。

**请求示例（顺便更新每日触发时间）**:
```bash
curl -X POST "http://localhost:8088/api/v1/opportunities/scan" \
  -H 'Content-Type: application/json' \
  -d '{"universe_name":"US_LARGE_MID_TECH","min_score":75,"max_results":3,"force_refresh":false,"schedule_cron":"30 20 * * *","schedule_timezone":"Asia/Shanghai"}' | jq
```

**响应说明**:
- `notes.idempotent=true`：表示命中幂等键，返回当日已生成结果
- `notes.macro_adjustment`：宏观风险 HIGH/EXTREME 时，阈值提高到 80 的信息
- `notes.universe`：股票池构建元信息（例如 cache_hit/fallback_used）

#### 11. GET /api/v1/opportunities/runs

查看最近 N 次扫描摘要。

**查询参数**:
- `limit` (int, optional): 默认 20
- `universe_name` (string, optional)

#### 12. GET /api/v1/opportunities/runs/{run_id}

查看某次扫描详情（含 items）。

---

### AI与行为评分

#### 13. GET /ai/state

获取账户当前 AI 风控状态（含 Greeks 暴露与行为画像）。

**查询参数**:
- `window_days` (int, optional): 覆盖窗口期（天）

#### 14. POST /ai/advice

生成 AI 决策建议。

#### 15. POST /admin/behavior/rebuild

重算最近 N 天行为评分。

**请求体**:
```json
{
  "account_id": "可选，默认 settings.TIGER_ACCOUNT",
  "window_days": 60
}
```

---

### 系统管理

#### 16. GET /admin/scheduler/jobs

查看所有定时任务状态。

**请求示例**:
```bash
curl "http://localhost:8088/admin/scheduler/jobs"
```

**响应示例**:
```json
{
  "status": "ok",
  "total_jobs": 7,
  "jobs": [
    {
      "id": "refresh_technical_indicators",
      "name": "刷新技术指标",
      "next_run_time": "2026-01-05 20:35:00",
      "trigger": "interval[1:00:00]"
    },
    {
      "id": "fetch_geopolitical_events",
      "name": "获取地缘政治事件",
      "next_run_time": "2026-01-05 20:40:00",
      "trigger": "interval[4:00:00]"
    },
    {
      "id": "calculate_macro_risk",
      "name": "计算宏观风险",
      "next_run_time": "2026-01-05 20:45:00",
      "trigger": "interval[6:00:00]"
    },
    {
      "id": "refresh_fundamental_data",
      "name": "刷新基本面数据",
      "next_run_time": "2026-01-06 02:00:00",
      "trigger": "cron[month='*', day='*', day_of_week='*', hour='2', minute='0']"
    },
    {
      "id": "cleanup_old_data",
      "name": "清理旧数据",
      "next_run_time": "2026-01-06 03:00:00",
      "trigger": "cron[month='*', day='*', day_of_week='*', hour='3', minute='0']"
    },
    {
      "id": "refresh_macro_indicators",
      "name": "刷新宏观指标",
      "next_run_time": "2026-01-06 09:00:00",
      "trigger": "cron[month='*', day='*', day_of_week='*', hour='9', minute='0']"
    },
    {
      "id": "scan_daily_opportunities_tech",
      "name": "每日机会扫描-科技股(20:30)",
      "next_run_time": "2026-01-06 20:30:00",
      "trigger": "cron[month='*', day='*', day_of_week='*', hour='20', minute='30']"
    }
  ]
}
```

---

#### 17. POST /admin/scheduler/jobs/{job_id}/pause

暂停指定的定时任务。

**请求示例**:
```bash
curl -X POST "http://localhost:8088/admin/scheduler/jobs/calculate_macro_risk/pause"
```

#### 18. POST /admin/scheduler/jobs/{job_id}/resume

恢复指定的定时任务。

**请求示例**:
```bash
curl -X POST "http://localhost:8088/admin/scheduler/jobs/calculate_macro_risk/resume"
```

---

#### 19. PUT /admin/scheduler/jobs/{job_id}/schedule

更新指定定时任务的执行时间和时区配置。

**路径参数**:
- `job_id` (string, required): 任务ID，如 "scan_daily_opportunities_tech"

**请求体**:
```json
{
  "hour": 20,
  "minute": 30,
  "timezone": "Asia/Shanghai"
}
```

**请求字段**:
- `hour` (int, required): 小时，范围 0-23
- `minute` (int, required): 分钟，范围 0-59
- `timezone` (string, optional): 时区，默认 "Asia/Shanghai"，支持标准时区名称如：
  - `Asia/Shanghai` - 北京时间 (UTC+8)
  - `America/New_York` - 纽约时间 (UTC-5/-4)
  - `Europe/London` - 伦敦时间 (UTC+0/+1)
  - `Asia/Tokyo` - 东京时间 (UTC+9)
  - `UTC` - 协调世界时

**请求示例**:
```bash
curl -X PUT "http://localhost:8088/admin/scheduler/jobs/scan_daily_opportunities_tech/schedule" \
  -H "Content-Type: application/json" \
  -d '{"hour": 21, "minute": 0, "timezone": "Asia/Shanghai"}'
```

**响应示例**:
```json
{
  "status": "success",
  "message": "Job schedule updated successfully. Next run: 2026-01-06 21:00:00",
  "job": {
    "id": "scan_daily_opportunities_tech",
    "name": "每日机会扫描-科技股(21:00)",
    "next_run_time": "2026-01-06 21:00:00",
    "trigger": "cron[month='*', day='*', day_of_week='*', hour='21', minute='0']",
    "timezone": "Asia/Shanghai",
    "status": "active"
  }
}
```

**响应字段**:
- `status`: 操作状态 (success/error)
- `message`: 操作结果消息
- `job`: 更新后的任务信息
  - `id`: 任务ID
  - `name`: 任务名称
  - `next_run_time`: 下次运行时间
  - `trigger`: 触发器配置
  - `timezone`: 时区
  - `status`: 任务状态

**注意事项**:
1. 配置更新后立即生效，会重新计算下次运行时间
2. 时区变更可能导致任务执行时间发生显著变化，请仔细核对
3. 建议选择市场非交易时段执行扫描任务
4. 北京时间 20:30 对应美股盘后，是扫描次日机会的理想时间

---

## 数据模型

### 风险等级 (Risk Level)

- `LOW`: 低风险，评分 > 80
- `MEDIUM`: 中等风险，评分 60-80
- `HIGH`: 高风险，评分 40-60
- `EXTREME`: 极高风险，评分 < 40

### 事件严重性 (Severity)

部分子模块（例如地缘事件）使用严重性字段，枚举通常为：

- `LOW` / `MEDIUM` / `HIGH` / `CRITICAL`

### 操作建议 (Recommendation)

- `STRONG_BUY`: 强烈买入，评分 > 85
- `BUY`: 买入，评分 75-85
- `HOLD`: 持有，评分 40-75
- `SELL`: 卖出，评分 25-40
- `STRONG_SELL`: 强烈卖出，评分 < 25

### 趋势方向 (Trend Direction)

- `BULLISH`: 看涨/上升趋势
- `BEARISH`: 看跌/下降趋势
- `SIDEWAYS`: 横盘/震荡

### 经济周期阶段 (Economic Cycle Phase)

- `衰退期 (Recession)`: GDP下降，失业率上升
- `复苏期 (Recovery)`: GDP回升，失业率开始下降
- `繁荣期 (Expansion)`: GDP高增长，失业率低
- `滞胀期 (Stagflation)`: GDP低增长，通胀高

### 货币政策立场 (Policy Stance)

- `宽松 (Accommodative)`: 低利率，刺激经济
- `中性 (Neutral)`: 平衡状态
- `紧缩 (Restrictive)`: 高利率，抑制通胀

---

## 错误处理

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

### HTTP 状态码

- `200 OK`: 请求成功
- `400 Bad Request`: 请求参数错误
- `404 Not Found`: 资源不存在
- `500 Internal Server Error`: 服务器内部错误

### 常见错误

#### 1. 股票代码不存在
```json
{
  "detail": "Technical data not found for INVALID"
}
```

#### 2. 数据源连接失败
```json
{
  "detail": "Error fetching fundamental analysis: Connection timeout"
}
```

#### 3. 参数验证失败
```json
{
  "detail": "window_days must be between 1 and 365"
}
```

---

## 配置说明

### 环境变量

在 `.env` 文件中配置以下变量：

```bash
# 数据库
DATABASE_URL=sqlite+aiosqlite:///./demo.db  # 当前实现中数据库连接在 backend/app/main.py 内固定

# 交易模式
TRADE_MODE=DRY_RUN  # OFF / DRY_RUN / REAL

# Tiger Broker API (可选)
TIGER_ACCOUNT=your_account
TIGER_ID=your_tiger_id
TIGER_PRIVATE_KEY_PATH=/abs/path/to/private_key.pem
TIGER_QUOTE_MODE=DELAYED  # DELAYED / REALTIME
QUOTE_DATA_WARNING=true

# 数据源API密钥
FRED_API_KEY=your_fred_api_key  # 可选，用于宏观经济数据
NEWS_API_KEY=your_news_api_key  # 可选，用于地缘政治事件
OPENAI_API_KEY=your_openai_key  # 可选，用于AI分析
OPENAI_MODEL=gpt-4
OPENAI_MAX_TOKENS=500
OPENAI_TIMEOUT_SECONDS=30

# 缓存配置
CACHE_TTL_TECHNICAL_HOURS=1
CACHE_TTL_FUNDAMENTAL_HOURS=24
CACHE_TTL_MACRO_HOURS=6
CACHE_TTL_GEOPOLITICAL_HOURS=4
```

### 数据源说明

1. **yfinance**: 免费，提供股票价格和基本面数据
2. **FRED API**: 需要API密钥（免费申请），提供宏观经济指标
3. **News API**: 需要API密钥（有免费额度），提供新闻事件
4. **OpenAI**: 需要API密钥（付费），提供AI分析摘要

---

## 使用示例

### Python 示例

```python
import requests
import json

base_url = "http://localhost:8088"

# 1. 检查服务健康状态
response = requests.get(f"{base_url}/health")
print(response.json())

# 2. 获取持仓评估
response = requests.get(
    f"{base_url}/api/v1/positions/assessment",
    params={"window_days": 7}
)
positions = response.json()
print(f"总持仓数: {positions['summary']['total_positions']}")

# 3. 获取AAPL技术分析
response = requests.get(
    f"{base_url}/api/v1/positions/AAPL/technical",
    params={"timeframe": "1d"}
)
technical = response.json()
print(f"趋势: {technical['trend_direction']}")
print(f"RSI: {technical['rsi']}")

# 4. 获取宏观风险概览
response = requests.get(f"{base_url}/api/v1/macro/risk/overview")
risk = response.json()
print(f"风险等级: {risk['overall_risk']['level']}")
print(f"风险评分: {risk['overall_risk']['score']}")

# 5. 刷新数据
response = requests.post(f"{base_url}/api/v1/positions/refresh")
print(response.json()['message'])
```

### JavaScript 示例

```javascript
const baseUrl = 'http://localhost:8088';

// 获取持仓评估
async function getPositionsAssessment() {
  const response = await fetch(`${baseUrl}/api/v1/positions/assessment?window_days=7`);
  const data = await response.json();
  console.log('持仓评估:', data);
  return data;
}

// 获取技术分析
async function getTechnicalAnalysis(symbol) {
  const response = await fetch(
    `${baseUrl}/api/v1/positions/${symbol}/technical?timeframe=1d`
  );
  const data = await response.json();
  console.log(`${symbol} 技术分析:`, data);
  return data;
}

// 获取宏观风险
async function getMacroRisk() {
  const response = await fetch(`${baseUrl}/api/v1/macro/risk/overview`);
  const data = await response.json();
  console.log('宏观风险:', data);
  return data;
}

// 使用示例
(async () => {
  await getPositionsAssessment();
  await getTechnicalAnalysis('AAPL');
  await getMacroRisk();
})();
```

### cURL 示例

```bash
# 健康检查
curl http://localhost:8088/health

# 持仓评估（格式化输出）
curl "http://localhost:8088/api/v1/positions/assessment?window_days=7" | jq

# 技术分析
curl "http://localhost:8088/api/v1/positions/AAPL/technical?timeframe=1d" | jq

# 基本面分析
curl "http://localhost:8088/api/v1/positions/AAPL/fundamental" | jq

# 宏观风险概览
curl "http://localhost:8088/api/v1/macro/risk/overview" | jq

# 货币政策分析
curl "http://localhost:8088/api/v1/macro/monetary-policy" | jq

# 地缘政治事件
curl "http://localhost:8088/api/v1/macro/geopolitical-events?days=7" | jq

# 刷新持仓数据
curl -X POST "http://localhost:8088/api/v1/positions/refresh"

# 刷新宏观数据
curl -X POST "http://localhost:8088/api/v1/macro/refresh"

# 查看定时任务
curl "http://localhost:8088/admin/scheduler/jobs" | jq

# 潜在机会：获取最新
curl "http://localhost:8088/api/v1/opportunities/latest" | jq

# 潜在机会：手动扫描
curl -X POST "http://localhost:8088/api/v1/opportunities/scan" \
  -H 'Content-Type: application/json' \
  -d '{"universe_name":"US_LARGE_MID_TECH","min_score":75,"max_results":3,"force_refresh":false}' | jq
```

---

## 性能考虑

### 缓存策略

- **技术指标**: 缓存 1 小时
- **基本面数据**: 缓存 24 小时
- **宏观指标**: 缓存 6 小时
- **地缘政治事件**: 缓存 4 小时

### 限流建议

建议在生产环境中添加限流：
- 单个IP每分钟最多 60 次请求
- 刷新接口每小时最多 10 次

### 并发处理

服务使用异步架构（FastAPI + SQLAlchemy async），支持高并发请求。

---

## 常见问题 (FAQ)

### Q1: 为什么有些API密钥是可选的？

A: 系统设计了多层降级策略：
- 没有FRED API密钥时，使用yfinance获取部分宏观数据
- 没有News API密钥时，返回空的地缘政治事件列表
- 没有OpenAI API密钥时，使用规则引擎生成分析摘要

### Q2: 数据多久更新一次？

A: 定时任务自动更新：
- 技术指标: 每小时
- 地缘政治事件: 每4小时
- 宏观风险: 每6小时
- 基本面数据: 每天凌晨2点
- 宏观指标: 每天早上9点

也可以通过refresh接口手动触发更新。

### Q3: 评分标准是什么？

A: 所有评分都是0-100分制：
- 0-40: 差/高风险
- 40-60: 一般/中等风险
- 60-80: 良好/低风险
- 80-100: 优秀/极低风险

### Q4: 如何解释宏观风险评分？

A: 宏观风险评分是加权平均：
- 货币政策风险 × 30%
- 地缘政治风险 × 20%
- 行业泡沫风险 × 20%
- 经济周期风险 × 20%
- 市场情绪风险 × 10%

评分越高表示风险越低（安全性越高）。

### Q5: AI摘要是实时生成的吗？

A: 首次请求时生成并缓存，后续请求直接返回缓存结果。缓存时间与数据类型相同。

---

## 更新日志

### v8.1.0 (2026-01-05)

**新增功能**:
- ✅ 潜在机会模块（run + items 落库、动态股票池、市值/行业筛选、Top 1–3 推荐）
- ✅ 每日自动机会扫描任务（北京时间 20:30，job_id=`scan_daily_opportunities_tech`）

**行为变化 / 修正**:
- 🛠️ Scheduler 管理接口以 job 维度 pause/resume（`/admin/scheduler/jobs/{job_id}/pause|resume`）
- 🛠️ 文档同步：补齐 opportunities 端点与 scheduler 返回结构（`trigger` 为字符串表达）

---

### v8.0.0 (2026-01-04)

**新增功能**:
- ✅ 持仓技术面和基本面分析API
- ✅ 宏观风险5维度评估系统
- ✅ 货币政策和经济周期分析
- ✅ 地缘政治事件追踪
- ✅ AI驱动的智能分析摘要
- ✅ 定时任务调度系统
- ✅ 6个自动化数据刷新任务

**技术栈**:
- FastAPI 0.115.12
- SQLAlchemy 2.0.42 (异步)
- yfinance 1.0
- pandas-ta (技术指标)
- fredapi 0.5.2 (宏观数据)
- newsapi-python 0.2.7 (新闻事件)
- openai 2.14.0 (AI分析)

---

## 联系支持

如有问题或建议，请通过以下方式联系：

- GitHub Issues: [项目地址]
- Email: [support email]
- 文档更新: 2026-01-05

---

**注意**: 本文档基于开发版本编写，生产环境部署前请确保：
1. 配置所有必要的API密钥
2. 启用认证和限流
3. 使用生产级数据库（PostgreSQL）
4. 配置HTTPS证书
5. 设置监控和日志系统
