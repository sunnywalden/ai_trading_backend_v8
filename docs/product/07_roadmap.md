<!-- 源自 docs/PRODUCT.md §7. 路线图 -->

## 7. 路线图

### Phase 1–5: 已完成 ✅
- 核心闭环、AI 决策、实时化、策略库、自适应优化

### Phase 6: 研究基础设施 🚀 V10 当前
- **回测引擎**：事件驱动，Walk-Forward，支持10类股票策略
- **DataHub**：Tiger → Polygon → yfinance 优先级路由
- **Paper Trading 账户隔离**：独立 account_id，模拟/实盘双轨

### Phase 7: AI 自主闭环核心 🚀 V10 核心
- **AI_AUTONOMY_LEVEL 三模式**（FULL / SEMI / ADVISORY）
- **组合级决策**（Markowitz + Kelly + 风险门禁）
- **压力测试**（5个历史情景 + 自定义）
- **Paper→Live 自动升级机制**（回测通过 + PA验证）
- **熔断机制 + 操作撤销**（SEMI 模式30分钟窗口）

### Phase 8: AI 深度升级 🚀 V10 当前
- **Trading Copilot**：对话式人机接口，替代散落的按钮
- **AI 自动周报/日报**：Telegram + 系统内存档
- **决策可解释性**：每笔交易 `reasoning` 字段 + 审计日志
- **AI 模型路由**：deepseek-chat/gpt-4o-mini（轻量）+ deepseek-reasoner/gpt-5.2（复杂）

### Phase 9: 执行精细化 🚀 V10 当前
- **TWAP/VWAP 自动路由**（AI 按订单大小自动选择）
- **期权分析中心**（只读信息工具，不执行）：IV曲面、P/C Ratio、异常成交

### Phase 10: 标的扩展 🚀 V10.1 当前
- **ETF 正式支持**（`STOCK,ETF` 模式）：行业轮动 + CTA 商品策略真正运行
- **港股 & 期权行情统一走 Tiger API**：港股（HK 市场）及期权行情数据优先通过老虎证券 API 获取，与美股股票保持一致的 DataHub 路由策略（Tiger → yfinance fallback），不引入 Futu API
- **Tiger 真实下单（美股 + 港股 + 期权）**：TigerOrderExecutor 完整实现，支持 US / HK 双市场及期权下单，FULL 模式实盘可用
- **FULL 模式完整自主闭环**：无需人工干预，AI 自主完成决策→下单→审计
- **Copilot 执行落地**：止损修改 / TWAP 下单 / 清仓三类指令实际执行
- **Dashboard 真实化**：VaR、宏观风险、执行指标、策略统计全部消除占位符
- **AI 组合级决策**：批量信号统一组合视角决策 + JSON 结构化输出消除 regex
- **Paper→Live 毕业自动化**：定时任务检测 + 自动升级
- **Dashboard WebSocket**：实时增量推送，降低延迟至 5s

### Phase 11: 全链路可观测性 ✅ V10.3 完成
- **Trade Lifecycle Center**：17阶段 PipelineKanban + DualFSM 双状态机可视化
- **Intelligent Order Book**：高密度全量订单列表，统一替代 AI Advisor + Journal 孤岛视图
- **Decision Provenance Drawer**：信号 → 风控 → 执行完整因果链溯源
- **Situational Awareness Bar**：全局粘性态势感知栏（体制/VaR/围栏/队列/模式）
- **执行幂等主键**：`autonomous_execution_intent` + 状态机（V10.3.2）
- **信号数量语义统一**：`quantity_mode + quantity_value` 标准化（V10.3.2）

### Phase 12: AI可观测性 & 指挥室 → 稳定性治理 ✅ V10.3.3 ~ V10.3.4 已完成（归档）
- **Execution Microscope**：Implementation Shortfall 四分解（迟延/市场冲击/机会/时机成本）
- **Signal Intelligence Observatory**：Alpha Decay 信号半衰期 + 因子相关矩阵 + 拥挤度检测
- **Risk Observability Cluster**：五因子实时敞口 + ES@97.5% 仪表 + 相关性骤升告警
- **Multi-Agent Orchestration**：五专职 Agent 协作框架（市场/风险/执行/研究/总协调）
- **AI Confidence Calibration**：Reliability Diagram + Brier/ECE + 自适应降评
- **Adaptive Factor Framework**：Kalman Filter 在线权重更新 + 因子动量加成
- **Decision Post-Mortem Engine**：事后剖析（反事实分析）+ 自动洞察反哺
- **War Room Mode**：全屏六格指挥视图 + 实时 P&L Ticker + 键盘快捷键
- **Intelligence Feed**：AI情报流（urgency 排序 + WebSocket 实时追加）
- **Portfolio Exposure Center**：行业/因子/地理敞口 + 相关矩阵
- **Smart Alert Center**：AI分级 + 告警聚合 + 建议行动

### Phase 13: 巩固、治理与完整性 ✅ V10.4 已完成（归档）
> 详细规划：[V10.4 Release Plan](../archived/v10/v10.4/RELEASE_PLAN_V10.4.md)

- **M1 数据闭环治理**：`actual_return` 自动回填 Job + IC 真实化（移除 fallback）+ 因子快照自动化 + 2026 年事件日历 + LLM 调用 `LLMCallGuard`
- **M2 UI 大清洗**：47 页 → ≤38 页，6 导航组 → 4 组，执行三页合并，双仪表盘合并，系统监控整合
- **M3 Copilot 全局化**：全局浮窗（Cmd+K）+ 页面上下文注入 + 实时系统状态 System Prompt
- **M4 自主循环稳定增强**：AutonomyHealthMonitor 自检 + JobWatchdog + Multi-Agent 真实并发 + WebSocket 重连
- **M4.1 系统监控增强**：`/system` 补齐交易生命周期监测、主数据流链路监测、模块与细粒度服务状态树，形成统一运维视图
- **M5 移动触达**：Dashboard/Alert/Copilot 三场景 375px 竖屏可用
- **M6 文档重构**：PRODUCT.md 拆分为模块化多文件，主文件 ≤300 行
- **★ V10.4.2 信号精英化**：五层信号漏斗 + Conviction Score + 多维共振门控 + 幽灵交易追踪 → 详细规划：[docs/archived/v10/v10.4/RELEASE_PLAN_V10.4.2.md](../archived/v10/v10.4/RELEASE_PLAN_V10.4.2.md)

### Phase 14: 机构级研究与交易纪律 ✅ V10.5.1 已交付
> 详细规划见：[docs/archived/v10/v10.5/RELEASE_PLAN_V10.5.1.md](../archived/v10/v10.5/RELEASE_PLAN_V10.5.1.md)

- **M1 Alpha Truth Stack**：策略/信号从 gross alpha 升级到 net alpha 真相治理，新增 Strategy Scorecard 2.0、信号衰减、影子组合、Purged Walk-Forward、成本后收益归因
- **M2 Portfolio Construction 2.0**：风险预算树 + 流动性感知 sizing + 边际 VaR/ES/turnover/alpha 贡献 + correlation cluster / sector / factor / event / liquidity 多约束组合构建
- **M3 Execution Policy Engine**：订单紧急度、参与率、滑点预算、预交易成本模型、child-order 调度、成交后 replay，正式把执行层从“下单路由”升级为“执行策略系统”
- **M4 Live Safety & Model Degradation Guard**：模型退化监控、数据新鲜度 kill matrix、券商执行完整性监控、自主度自适应降级（FULL → SEMI → ADVISORY）
- **M5 Research-to-Live Governance**：shadow live、策略晋级流水线、实验总账、上线/回滚证据链，确保策略和参数变更能被审计、验证、回溯
- **前端重点**：围绕 Alpha Lab、Portfolio Construction Console、Execution Policy Console、Promotion Pipeline Board 做决策级可视化，而非继续横向扩页
- **★ V10.5.1 补丁（已交付）**：事后决策剖析自动化（`post_mortem_jobs.py` EventBus + Cron) + 事件日历 freshness 修复 + `confirmed=False` 体制修复

### Phase 15: Profit Engine Upgrade 🚀 V10.5.3 当前规划
> 详细规划见：[docs/archived/v10/v10.5/RELEASE_PLAN_V10.5.3.md](../archived/v10/v10.5/RELEASE_PLAN_V10.5.3.md)

- **M1 Alpha Truth Engine 2.0**：建立 `gross / net / after cost / after turnover` 四层 alpha 真相口径，补齐 regime / capacity / decay / shadow false-reject 视图，解决“看起来赚钱”和“净成本后赚钱”之间的偏差
- **M2 Portfolio Construction 2.1**：以 `Seat Value` 为核心升级 `CapacityArbiter`，加入 Risk Budget Tree、Marginal Alpha/Risk/Turnover/Liquidity 贡献，让资本按边际净收益分配
- **M3 Execution Policy Closed Loop**：把 Pre-Trade Cost、slippage budget、urgency、participation rate 接入执行前决策，并让执行反馈回写 execution policy profile
- **M4 Research-to-Live Governance Hard Gate**：统一 `Discovery / Paper / Shadow Live / Challenger / Production` 五阶段晋级管线，以 evidence chain 驱动 promotion / rollback，而不是只看 paper 胜率
- **前端重点**：强化 `/alpha-lab`、`/portfolio`、`/execution-policy`、`/governance/pipeline` 四个决策工作台，继续坚持“决策级可视化而非页面膨胀”
- **与 V10.5.2 的关系**：V10.5.2 的席位竞争与容量替换逻辑作为 V10.5.3 的 M2 子模块吸收，不再作为单独主版本推进

### Phase 16: V11 计划 🔜
- 期权执行开启（`STOCK,ETF,OPTION` 全模式）
- 多账户 / 多用户支持
- LLM Fine-tuning 个人交易风格适配
- 实时 L2 订单簿深度分析
- 移动端原生 App（iOS/Android）
