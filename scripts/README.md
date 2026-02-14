# 脚本目录说明 (Scripts Directory)

本目录包含用于数据库初始化、数据迁移、系统维护及性能测试的各类脚本。

## 📁 目录结构

- **[migrations/](migrations/)**: 正式版本化迁移脚本目录 (v3.1.1+)。
- **[legacy_migrations/](legacy_migrations/)**: 历史遗留的一次性迁移脚本存档。

## 📊 脚本分类归纳

### 1. 数据库初始化 (Data Initialization)
用于系统首次部署或重置环境。
- **[init_db.py](init_db.py)**: 初始化基础数据库表结构。
- **[init_strategies.py](init_strategies.py)**: 初始化 15 个内置策略定义。
- **[init_v10_equity.py](init_v10_equity.py)**: 初始化 v10 权益快照数据。
- **[init_v9_demo_data.py](init_v9_demo_data.py)**: 注入 v9 版本的演示数据。

### 2. 历史数据迁移 (Legacy Migrations - 已移至存档)
存档在建立正式迁移系统之前的临时迁移脚本。
- **[migrate_asset_columns.py](legacy_migrations/migrate_asset_columns.py)**: 迁移资产列数据。
- **[migrate_evaluation_to_unique_symbol.py](legacy_migrations/migrate_evaluation_to_unique_symbol.py)**: 将评测逻辑从批次制改为唯一标的制。
- **[migrate_history_evaluation.sh](legacy_migrations/migrate_evaluation_history.sh)**: 迁移评测历史的 Shell 脚本。
- **[migrate_journal_signal_id.py](legacy_migrations/migrate_journal_signal_id.py)**: 同步交易日志中的信号 ID。
- **[migrate_hotspots.py](legacy_migrations/migrate_hotspots.py)**: 迁移热点数据。
- **[migrate_portfolio_columns.py](legacy_migrations/migrate_portfolio_columns.py)**: 迁移投资组合相关列。
- **[migrate_run_assets.py](legacy_migrations/migrate_run_assets.py)**: 迁移策略运行资产数据。
- **[upgrade_macd_status.py](legacy_migrations/upgrade_macd_status.py)**: 升级 MACD 状态字段长度和类型。

### 3. 表结构修复与调整 (Schema Fixes - 已移至存档)
- **[add_pnl_pct_column.py](legacy_migrations/add_pnl_pct_column.py)**: 添加盈亏百分比列。
- **[add_updated_at_column.py](legacy_migrations/add_updated_at_column.py)**: 为所有表添加 `updated_at` 时间戳。
- **[add_updated_at.sql](legacy_migrations/add_updated_at.sql)**: 配合上述 Python 脚本的原始 SQL。
- **[create_position_macro_tables.py](legacy_migrations/create_position_macro_tables.py)**: 创建持仓宏观相关的辅助表。
- **[fix_db_schema.py](legacy_migrations/fix_db_schema.py)**: 修复不一致的数据库 Schema。
- **[fix_strategy_runs_columns.py](legacy_migrations/fix_strategy_runs_columns.py)**: 修复策略运行记录的列定义。

### 4. 数据校验与完整性测试 (Checks & Verification)
用于验证系统逻辑或数据正确性。
- **[check_db_data.py](check_db_data.py)**: 综合性数据库数据一致性检查。
- **[check_filter_logic.py](check_filter_logic.py)**: 验证策略过滤逻辑。
- **[check_scores.py](check_scores.py)**: 校验评分引擎的输出。
- **[verify_price_fix.py](verify_price_fix.py)**: 验证价格修正逻辑是否生效。

### 5. 维护与性能工具 (Maintenance & Utilities)
- **[clean_duplicate_signals.py](clean_duplicate_signals.py)**: 清理数据库中的重复信号记录。
- **[clear_hk_name_cache.py](clear_hk_name_cache.py)**: 清除港股名称缓存。
- **[benchmark_p95.py](benchmark_p95.py)**: 接口 P95 响应时间基准测试。
- **[test_yf.py](test_yf.py)**: 测试 Yahoo Finance 行情源连接。

---

## ⚠️ 使用建议
1. 对于 v3.1.1 之后的版本，**请优先使用 `migrations/` 目录下的版本化脚本**。
2. 运行任何迁移或初始化脚本前，**请务必备份数据库**。
3. 历史迁移脚本（migrate_*.py）在生产环境执行过一次后通常不再需要，可以移动到存档目录。
