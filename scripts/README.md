# 脚本目录说明

本目录目前同时承载 5 类脚本：

1. **正式版本迁移脚本**：放在 `migrations/`
2. **历史一次性迁移脚本**：放在 `legacy_migrations/`
3. **通用运维 / 校验 / 修复脚本**：保留在 `scripts/` 根目录
4. **按版本整理的检索索引**：放在 `by_version/`
5. **已归档的历史现场脚本**：放在 `archived/`

> 为避免破坏现有命令、文档和上线流程，本次整理采用 **非破坏式归纳**：
> **先补全按版本索引，不直接变更现有脚本路径**。

## 📁 当前目录结构

- **[migrations/](migrations/)**：正式版本化迁移脚本（v3.1.1+）
- **[legacy_migrations/](legacy_migrations/)**：正式迁移体系建立前的历史脚本存档
- **[by_version/](by_version/)**：按版本归纳的脚本索引（推荐优先查看）
- **[archived/](archived/)**：按版本归档的历史现场脚本
- **根目录脚本**：初始化、巡检、诊断、修复、回填、验证、现场排障等工具

## 🧭 入口导航

如果你是第一次来这个目录，推荐直接从下面进入：

- **[by_version/README.md](by_version/README.md)**：总版本索引入口
- **[by_version/v3x.md](by_version/v3x.md)**：v3.x 相关脚本
- **[by_version/v9.md](by_version/v9.md)**：v9 相关脚本
- **[by_version/v10_2.md](by_version/v10_2.md)**：V10.2 相关脚本
- **[by_version/v10_3_x.md](by_version/v10_3_x.md)**：V10.3.x 相关脚本
- **[by_version/v10_4_x.md](by_version/v10_4_x.md)**：V10.4.x 相关脚本
- **[by_version/general.md](by_version/general.md)**：通用脚本归纳
- **[by_version/legacy.md](by_version/legacy.md)**：历史遗留迁移脚本归纳
- **[archived/README.md](archived/README.md)**：归档脚本入口

## 🔎 推荐查找顺序

当你要找某个版本相关脚本时，建议按下面顺序：

1. 先看 **[by_version/README.md](by_version/README.md)**
2. 再按版本进入对应分页面（如 `by_version/v10_4_x.md`）
3. 涉及数据库版本升级时，优先看 **[migrations/](migrations/)**
4. 涉及一次性历史迁移时，再看 **[legacy_migrations/](legacy_migrations/)**
5. 若脚本已归档，则进入 **[archived/README.md](archived/README.md)**
6. 通用诊断/修复脚本最后再回到 `scripts/` 根目录按用途查找

## 🧭 根目录脚本的功能归类

### 初始化 / 启动准备

- **[init_db.py](init_db.py)**：初始化基础数据库表结构
- **[init_strategies.py](init_strategies.py)**：初始化内置策略定义
- **[init_v10_equity.py](init_v10_equity.py)**：初始化 v10 权益快照数据
- **[init_v9_demo_data.py](init_v9_demo_data.py)**：注入 v9 演示数据

### 巡检 / 校验 / 验证

- **[check_db_data.py](check_db_data.py)**：综合性数据库一致性检查
- **[check_filter_logic.py](check_filter_logic.py)**：验证过滤逻辑
- **[check_scores.py](check_scores.py)**：评分输出校验
- **[check_schema.py](check_schema.py)**：数据库结构检查
- **[check_signal_state.py](check_signal_state.py)**：信号状态检查
- **[check_signals.py](check_signals.py)**：信号数据检查
- **[check_obs_data.py](check_obs_data.py)**：观测/可观测性数据检查
- **[verify_price_fix.py](verify_price_fix.py)**：价格修复验证
- **[verify_dashboard_data.py](verify_dashboard_data.py)**：看板数据验证
- **[verify_attribution_fix.py](verify_attribution_fix.py)**：归因修复验证
- **[verify_trigger_decision_cycle.py](verify_trigger_decision_cycle.py)**：触发-决策链路验证
- **[verify_m2_calendar.py](verify_m2_calendar.py)**：M2 日历验证
- **[verify_m2_fence.py](verify_m2_fence.py)**：M2 围栏验证

### 诊断 / 排障

- **[debug_plans.py](debug_plans.py)**：计划调试
- **[diag_data_flow.py](diag_data_flow.py)**：数据流排障
- **[diag_lifecycle.py](diag_lifecycle.py)**：交易生命周期排障
- **[diag_post_trade_loop.py](diag_post_trade_loop.py)**：post-trade 循环排障
- **[diag_signal_journal_link.py](diag_signal_journal_link.py)**：信号-日志链路排障
- **[diag_stage7_stuck_orders.py](diag_stage7_stuck_orders.py)**：Stage7 卡单诊断

### 修复 / 回填 / 维护

- **[fix_account_id_data.py](fix_account_id_data.py)**：账号维度历史数据修复（V10.3.3+）
- **[fix_copilot_schema.py](fix_copilot_schema.py)**：Copilot 相关结构修复
- **[fix_draft_journals.py](fix_draft_journals.py)**：草稿日志修复
- **[fix_order_book_stuck.py](fix_order_book_stuck.py)**：订单簿卡死修复
- **[cleanup_stuck_plans.py](cleanup_stuck_plans.py)**：清理卡住计划
- **[advance_stuck_plans.py](advance_stuck_plans.py)**：推进卡住计划
- **[rescue_queued_signals.py](rescue_queued_signals.py)**：抢救排队信号
- **[clean_duplicate_signals.py](clean_duplicate_signals.py)**：清理重复信号
- **[clear_hk_name_cache.py](clear_hk_name_cache.py)**：清理港股名称缓存
- **[force_daily_cycle.py](force_daily_cycle.py)**：强制触发日循环
- **[sync_broker_manual_cancels.py](sync_broker_manual_cancels.py)**：同步券商手动撤单
- **[backfill_autonomous_plan_fsm_logs.py](backfill_autonomous_plan_fsm_logs.py)**：回填自主计划 FSM 日志
- **[backfill_journal_from_autonomous_plans.py](backfill_journal_from_autonomous_plans.py)**：从自主计划回填日志
- **[backfill_journal_prices.py](backfill_journal_prices.py)**：回填交易日志价格
- **[migrate_attribution_traded_at.py](migrate_attribution_traded_at.py)**：归因字段时间迁移

### 性能 / 外部依赖 / 杂项

- **[benchmark_p95.py](benchmark_p95.py)**：接口 P95 性能基准
- **[test_yf.py](test_yf.py)**：测试 Yahoo Finance 行情源

### 现场临时脚本（已按版本归档，根目录保留兼容入口）

以下脚本主要用于本地/线上现场排障，带 `_tmp_` 前缀。

- 实际脚本已迁入 **`archived/v10_4_3/`**
- 归档入口说明见 **[archived/README.md](archived/README.md)**
- 根目录仍保留同名包装脚本，旧命令可继续执行

已归档脚本：

- `_tmp_check_and_fix_three_failed.py`
- `_tmp_check_fsm_type_counts.py`
- `_tmp_check_s12.py`
- `_tmp_check_three_status.py`
- `_tmp_failed_three_detail.py`
- `_tmp_run_broker_sync.py`
- `_tmp_stage7_diagnose.py`
- `_tmp_stage7_evidence.py`
- `_tmp_system_monitor_inspect.py`

## 🗂️ 按版本归纳入口

- **[by_version/README.md](by_version/README.md)**：版本总索引

进一步可按版本进入：

- **[by_version/v3x.md](by_version/v3x.md)**
- **[by_version/v9.md](by_version/v9.md)**
- **[by_version/v10_2.md](by_version/v10_2.md)**
- **[by_version/v10_3_x.md](by_version/v10_3_x.md)**
- **[by_version/v10_4_x.md](by_version/v10_4_x.md)**
- **[by_version/general.md](by_version/general.md)**
- **[by_version/legacy.md](by_version/legacy.md)**

其中重点整理了：

- `v3.x` 基线迁移脚本
- `v9` 初始化脚本
- `v10.2` 迁移脚本
- `v10.3.x` 升级 / 验收 / 数据修复脚本
- `v10.4.x` 升级 / 验收 / 生命周期与监控上线辅助脚本

## ⚠️ 使用建议

1. **数据库版本升级优先使用 `migrations/`**，不要拿根目录临时脚本替代正式迁移。
2. 运行迁移、批量修复、回填脚本前，**先备份数据库**。
3. `_tmp_*` 脚本已开始迁入 `archived/`；如需追溯原始内容，优先查看归档目录。
4. 如果某脚本绑定某个版本波次，优先从 `by_version/README.md` 查询其上下文，再执行。
