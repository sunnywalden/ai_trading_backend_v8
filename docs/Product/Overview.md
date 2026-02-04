# 产品概览（后端视角）

AI Trading Backend V8 由四个相对独立的能力簇组成：

1) **风险管理与自动对冲**（Greeks 暴露、限额、自动生成对冲方案）
2) **行为画像与行为评分**（从历史成交/盈亏抽取“卖飞、过度交易、报复性交易”等）
3) **持仓评估**（技术面 + 基本面 + 情绪/风险合成，输出建议与关键价位）
4) **宏观风险与机会扫描**（宏观风险概览 + Opportunities 每日扫描）
5) **交易计划**（计划创建/更新/执行状态）

## 关键产品约束（必须写进文档的“口径”）

- **宏观分析与短期趋势不联动**：宏观风险模块独立输出，不直接参与日线趋势判断。
- **趋势快照持久化**：日线走势分析会写入 `position_trend_snapshots`（每日每标的留最新快照），供持仓评估接口直接读取。
- **不输出“趋势信心/可信度”数值**：日线走势结论强调交易员风格与可执行条件触发，不返回趋势置信度字段。

## 持仓评估（Positions Assessment）

- 输入：账户持仓（来自 Tiger 或 Dummy）
- 计算：
  - 技术分析（含趋势/RSI/MACD/布林/支撑阻力/量比）
  - 基本面分析
  - 合成评分与建议
- 输出：`GET /api/v1/positions/assessment` 返回每个标的的评分、建议与 `trend_snapshot`，并包含 `budget_utilization` / `plan_deviation`。

## 宏观风险（Macro Risk）

- 输出：`GET /api/v1/macro/risk/overview` 返回综合风险、分项风险、预警、建议、AI 解读（可降级）。
- 刷新：`POST /api/v1/macro/refresh`

## Opportunities（潜在机会）

- 输出：`GET /api/v1/opportunities/latest` 获取最新一次扫描结果（含计划匹配标签）
- 触发：`POST /api/v1/opportunities/scan` 支持即时扫描与可选更新 cron

## 策略筛选 (Strategy Screening)

- **策略扫描结果馈送**：展示可执行的中短期交易逻辑扫描结果，包括平台预置的私募精选策略。
- **内置华尔街私募精选策略**：复刻多个中短期精选标的策略，捕捉 alpha。
- **不再提供立即执行与历史记录**：改为展示最新的异步扫描结果。