# 历史遗留迁移脚本归纳

这组脚本属于正式版本化迁移体系建立前的历史一次性迁移脚本，统一位于 `../legacy_migrations/`。

## 脚本列表

- `../legacy_migrations/add_pnl_pct_column.py`
- `../legacy_migrations/add_updated_at_column.py`
- `../legacy_migrations/add_updated_at.sql`
- `../legacy_migrations/create_position_macro_tables.py`
- `../legacy_migrations/fix_db_schema.py`
- `../legacy_migrations/fix_strategy_runs_columns.py`
- `../legacy_migrations/migrate_asset_columns.py`
- `../legacy_migrations/migrate_evaluation_history.sh`
- `../legacy_migrations/migrate_evaluation_to_unique_symbol.py`
- `../legacy_migrations/migrate_hotspots.py`
- `../legacy_migrations/migrate_journal_signal_id.py`
- `../legacy_migrations/migrate_portfolio_columns.py`
- `../legacy_migrations/migrate_run_assets.py`
- `../legacy_migrations/upgrade_macd_status.py`

## 使用建议

1. 这类脚本通常只适用于历史环境修复或回溯，不建议直接纳入当前主线生产 SOP。
2. 如遇老库恢复、历史环境迁移，再结合具体表结构审慎使用。
