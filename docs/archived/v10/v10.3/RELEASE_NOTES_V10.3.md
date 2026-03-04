# V10.3 / V10.3.4 版本总结归档

> **AI量化交易闭环系统** — V10.3.x 归档  
> 归档日期：2026-03-04  
> 最终版本：V10.3.4（tag: v10.3.4）

---

## V10.3 — 交易全链路可观测性（Full Trade Observability）

**核心命题**：让 AI 的每一个动作都在玻璃墙后面运行。

**已交付**：
- Trade Lifecycle Center（`/trade-lifecycle`）：17阶段 PipelineKanban + DualFSM 双状态机
- Intelligent Order Book（`/order-book`）：高密度全量订单列表，替代 AI Advisor + Journal 孤岛视图
- Decision Provenance Drawer：信号 → 风控 → 执行完整因果链六步溯源
- Situational Awareness Bar：全局粘性态势感知栏（体制/VaR/围栏/队列/模式）

## V10.3.2 — 执行幂等主键

**已交付**：
- `autonomous_execution_intent` 表 + `idempotency_key` 唯一约束
- 统一执行入口状态机：PENDING → EXECUTING → SUCCESS/FAILED/SKIPPED/REJECTED
- 信号数量语义统一：`quantity_mode + quantity_value`

## V10.3.3 — 可观测性 2.0 + AI 中枢 2.0 + 指挥室

**已交付（前端页面已建，后端服务已建）**：

| 功能模块 | 后端服务 | 前端页面 | 数据完整性 |
|---------|---------|---------|-----------|
| Execution Microscope | `execution_microscope_service.py` | `ExecutionMicroscopePage.vue` | IS 分解需要真实成交数据 |
| Signal Intelligence Observatory | `signal_intelligence_service.py` | `SignalIntelligencePage.vue` | IC 计算依赖 `actual_return`（目前多为 null） |
| Risk Observability Cluster | `risk_observability_service.py` | `RiskClusterPage.vue` | 因子敞口计算已实现，快照写入每5分钟 |
| Multi-Agent Orchestration | `multi_agent_orchestrator.py` | `MultiAgentPage.vue` | AgentMessage 通信日志已落库 |
| AI Confidence Calibration | `confidence_calibration_service.py` | `CalibrationPage.vue` | 需90日历史数据积累 |
| Adaptive Factor Framework | `adaptive_factor_weighting_service.py` | `FactorWeightsPage.vue` | Kalman 权重已更新，依赖 IC 数据 |
| Decision Post-Mortem Engine | `decision_post_mortem_service.py` | `PostMortemPage.vue` | 需平仓触发，积累中 |
| War Room Mode | `war_room_service.py` | `WarRoomPage.vue` | P&L Ticker + Intelligence Feed 已实现 |
| Smart Alert Center | `smart_alert_service.py` | DashboardV2 内嵌 | AI 分级告警已实现 |

**遗留问题（进入 V10.3.4 修复，下方见详情）**：
- `TradingSignal.actual_return` 大量为 null → IC/Alpha Decay 计算依赖回填脚本手动触发（V10.4 M1 修复）
- Signal Intelligence 的 IC 序列依赖完整归因链闭合，归因链在无成交数据时退化为 fallback（V10.4 M1 修复）
- Risk Observability 快照需手动 `seed_snapshot_from_live_data`，自动化任务未完全就绪（V10.4 M1 修复）
- 前端存在多组重复/遗留页面尚未清理（见 V10.4 UI 治理计划）

---

## V10.3.4 — 稳定性与冷启动治理（Stability & Cold-Start Governance）

**核心命题**：在 V10.3.3 建立的观测体系上，修复所有"有界面但没数据"的冷启动空白，覆盖多账户场景，并新增市场全量标的池。

**已交付新功能**：

| 功能模块 | 变更说明 |
|---------|---------|
| **市场全量股票池（Market Universe Pool）** | 新增 `market_universe` 表 + `MarketUniverseService`，支持美股/港股全量标的定时同步与缓存；`GET /api/v1/market-universe/status` 返回同步状态与活跃标的数 |
| **决策事后剖析升级** | `PostMortemService` 从手工录入模式升级为交易选择驱动（选择历史 TradeJournal 记录 → 自动触发 LLM 反事实分析）|
| **AI 决策信号深化** | 自主引擎新增 REDUCE/EXIT 信号规则执行路径；`HOLD/qty≤0` 由 `EXECUTED` 纠偏为 `SKIPPED`，no-op 原因分类落库 |
| **信号数量语义完整** | 信号管道 `quantity_mode/quantity_value` 字段全链路透传标准化 |

**稳定性修复（冷启动 & 零数据场景）**：

| 服务 | 修复内容 |
|-----|---------|
| Dashboard 服务 | 无快照时返回零值占位数据，不报错 |
| 代理运行状态接口 | 未运行时返回 `status=cold_start`，消除前端轮询 404 抖动 |
| 执行质量记录查询 | 无历史数据时返回空列表占位，不报错 |
| 置信度校准快照 | 支持原地更新已有快照 + 重复检测（唯一约束保护）|
| MultiAgent 上下文管理 | Session 独立化，防止跨决策周期上下文泄漏 |

**多账户兼容性修复**：

- 告警服务（`AlertService`）、仪表板（`DashboardService`）、归因分析（`TradeAttributionService`）、量化闭环（`QuantLoopService`）统一账户 ID 解析逻辑
- 审计日志接口新增分页支持

**事件系统修复**：

- `event_calendar` 表新增 `(symbol, event_date, event_type)` 唯一联合索引
- 事件写入前执行 `INSERT OR IGNORE` 去重，防止重复事件累积
- 围栏统计接口新增 `lookahead_days` 参数配置

**DB 迁移**：
- `v10.3.4_add_market_universe_table`：新增 `market_universe` 表（`symbol`, `market`, `name`, `is_active`, `last_synced_at`）
