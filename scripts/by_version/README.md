# 脚本版本索引

本索引用于按版本波次快速定位 `scripts/` 下的相关脚本。

> 说明：
>
> - 当前索引已与新的脚本子目录结构同步。
> - **正式数据库升级** 优先看 `scripts/migrations/`。
> - 非迁移脚本已按用途迁入 `bootstrap/`、`checks/`、`diagnostics/`、`maintenance/`、`performance/`、`sql/`。

## 目录导航

- **[v3x.md](v3x.md)**：v3.x 基线迁移脚本
- **[v9.md](v9.md)**：v9 演示数据相关脚本
- **[v10_2.md](v10_2.md)**：V10.2 波次脚本
- **[v10_3_x.md](v10_3_x.md)**：V10.3.x 波次脚本
- **[v10_4_x.md](v10_4_x.md)**：V10.4.x 波次脚本
- **[v10_5_x.md](v10_5_x.md)**：V10.5.x 波次脚本
- **[general.md](general.md)**：通用脚本归纳
- **[legacy.md](legacy.md)**：历史遗留迁移脚本

## v3.x 基线迁移

| 版本 | 脚本 | 说明 |
| --- | --- | --- |
| v3.1.1 | `migrations/upgrade_to_v3.1.1.py` | 数据库升级脚本 |
| v3.1.1 | `migrations/verify_v3.1.1.py` | 升级后结构验证 |
| v3.1.1 | `migrations/rollback_from_v3.1.1.py` | 从 v3.1.1 回滚 |
| v3.2.1 | `migrations/upgrade_to_v3.2.1.py` | 数据库升级脚本 |
| v3.2.1 | `migrations/verify_v3.2.1.py` | 升级后结构验证 |
| v3.x 通用 | `migrations/version_manager.py` | 版本记录管理 |

## v9

| 版本 | 脚本 | 说明 |
| --- | --- | --- |
| v9 | `bootstrap/init_v9_demo_data.py` | v9 演示数据初始化 |

## v10.2

| 版本 | 脚本 | 说明 |
| --- | --- | --- |
| v10.2 M1 | `migrations/upgrade_to_v10_2_m1.py` | V10.2 M1 升级 |
| v10.2 M2 / M8 | `migrations/upgrade_to_v10_2_m2_m8.py` | V10.2 M2/M8 升级 |
| v10.2 通用 | `checks/verify_m2_calendar.py` | M2 日历验证 |
| v10.2 通用 | `checks/verify_m2_fence.py` | M2 围栏验证 |

## v10.3.x

| 版本 | 脚本 | 说明 |
| --- | --- | --- |
| v10.3 | `migrations/upgrade_to_v10_3.py` | V10.3 升级 |
| v10.3.2 | `checks/check_v10_3_2_data.py` | V10.3.2 数据验收（只读） |
| v10.3.3 | `migrations/upgrade_to_v10_3_3.py` | V10.3.3 升级 |
| v10.3.3+ | `maintenance/fix_account_id_data.py` | user_id → account_id 历史数据修复 |
| v10.3.4 | `migrations/upgrade_to_v10_3_4.py` | V10.3.4 升级 |

### v10.3.x 辅助脚本

这些脚本未必只服务于单一补丁版本，但主要活跃于 V10.3 交易链路与归因/日志治理阶段：

- `maintenance/migrate_attribution_traded_at.py`
- `checks/check_attribution_data.py`
- `checks/verify_attribution_fix.py`
- `checks/verify_price_fix.py`
- `checks/verify_trigger_decision_cycle.py`
- `checks/check_signal_state.py`
- `checks/check_signals.py`

## v10.4.x

| 版本 | 脚本 | 说明 |
| --- | --- | --- |
| v10.4.1 | `migrations/upgrade_to_v10_4_1.py` | V10.4.1 升级 |
| v10.4.1 | `checks/_acceptance_v10_4_1.py` | V10.4.1 验收测试 |
| v10.4.2 | `migrations/upgrade_to_v10_4_2.py` | V10.4.2 升级 |

### V10.4.3 生命周期 / 系统监控上线波次

以下脚本与最近的生命周期、系统监控、对账、日志回填治理强相关，可归入 **V10.4.3 上线辅助脚本集合**：

- `maintenance/reconcile_lifecycle_rollout.py`：生产上线辅助，归正交易生命周期终态语义
- `maintenance/sync_broker_manual_cancels.py`：同步券商手动撤单
- `checks/check_manual_cancel_sync_result.py`：校验手动撤单同步结果
- `maintenance/backfill_autonomous_plan_fsm_logs.py`：回填自主计划 FSM 日志
- `maintenance/backfill_journal_from_autonomous_plans.py`：从自主计划回填日志
- `maintenance/backfill_journal_prices.py`：回填日志价格
- `checks/check_plan_journal_alignment.py`：校验计划与日志对齐
- `checks/verify_lifecycle_and_journal_visibility.py`：验证生命周期与日志页面可见性
- `diagnostics/diag_lifecycle.py`：生命周期诊断
- `diagnostics/diag_post_trade_loop.py`：post-trade 诊断
- `diagnostics/diag_signal_journal_link.py`：信号到日志链路诊断
- `diagnostics/diag_stage7_stuck_orders.py`：Stage7 卡单诊断
- `maintenance/cleanup_stuck_plans.py`：清理卡住计划
- `maintenance/advance_stuck_plans.py`：推进卡住计划
- `maintenance/rescue_queued_signals.py`：抢救排队信号
- `maintenance/fix_draft_journals.py`：修复草稿日志

### V10.4.3 现场临时排障脚本

以下 `_tmp_*` 脚本主要服务于最近一轮 V10.4.3 生命周期 / 系统监控现场排障，现已归档到 `archived/v10_4_3/`：

- `archived/v10_4_3/_tmp_system_monitor_inspect.py`
- `archived/v10_4_3/_tmp_run_broker_sync.py`
- `archived/v10_4_3/_tmp_stage7_diagnose.py`
- `archived/v10_4_3/_tmp_stage7_evidence.py`
- `archived/v10_4_3/_tmp_failed_three_detail.py`
- `archived/v10_4_3/_tmp_check_three_status.py`
- `archived/v10_4_3/_tmp_check_and_fix_three_failed.py`
- `archived/v10_4_3/_tmp_check_s12.py`
- `archived/v10_4_3/_tmp_check_fsm_type_counts.py`

## v10.5.x

| 版本 | 脚本 | 说明 |
| --- | --- | --- |
| v10.5.1 | `migrations/upgrade_to_v10_5_1.py` | V10.5.1 升级 |
| v10.5.2 | `migrations/upgrade_to_v10_5_2.py` | V10.5.2 升级 |
| v10.5.3 | `migrations/upgrade_to_v10_5_3.py` | V10.5.3 升级（建 execution_policy_profiles） |
| v10.5.3 | `migrations/backfill_execution_policy_profiles.py` | 回填长期执行画像 |
| v10.5.3 | `maintenance/repair_execution_policy_profiles.py` | 校验并修复执行画像数据 |

详见：**[v10_5_x.md](v10_5_x.md)**

## 通用脚本（不强绑定单一版本）

这些脚本更适合作为长期通用工具使用，不建议强行塞进某个补丁版本：

- `bootstrap/init_db.py`
- `bootstrap/init_strategies.py`
- `bootstrap/init_v10_equity.py`
- `checks/check_db_data.py`
- `checks/check_filter_logic.py`
- `checks/check_obs_data.py`
- `checks/check_schema.py`
- `checks/check_scores.py`
- `checks/verify_dashboard_data.py`
- `performance/benchmark_p95.py`
- `maintenance/clean_duplicate_signals.py`
- `maintenance/clear_hk_name_cache.py`
- `maintenance/fix_copilot_schema.py`
- `maintenance/fix_order_book_stuck.py`
- `maintenance/force_daily_cycle.py`
- `diagnostics/debug_plans.py`
- `diagnostics/diag_data_flow.py`
- `performance/test_yf.py`

详见：**[general.md](general.md)**

## 历史遗留迁移脚本

正式版本化迁移体系建立前的历史脚本，统一放在 `legacy_migrations/`：

- `add_pnl_pct_column.py`
- `add_updated_at_column.py`
- `add_updated_at.sql`
- `create_position_macro_tables.py`
- `fix_db_schema.py`
- `fix_strategy_runs_columns.py`
- `migrate_asset_columns.py`
- `migrate_evaluation_history.sh`
- `migrate_evaluation_to_unique_symbol.py`
- `migrate_hotspots.py`
- `migrate_journal_signal_id.py`
- `migrate_portfolio_columns.py`
- `migrate_run_assets.py`
- `upgrade_macd_status.py`

详见：**[legacy.md](legacy.md)**

## 建议执行策略

1. **版本升级**：先查 `migrations/`，再查本索引里的对应版本辅助脚本。
2. **线上修复**：优先找带 `reconcile` / `sync` / `backfill` / `verify` 名称的脚本。
3. **现场排障**：`diag_*` 和 `_tmp_*` 仅建议用于问题定位，不建议长期纳入 SOP。
4. **版本发布完成后**：优先将对应波次的 `_tmp_*` 脚本迁入 `archived/<version>/`，避免根目录重新堆积一次性脚本。
