# 通用脚本归纳

这些脚本不强绑定某个单一版本，适合作为长期运维、巡检、初始化或排障工具。

## 初始化 / 基础准备

- `../bootstrap/init_db.py`：初始化数据库基础结构
- `../bootstrap/init_strategies.py`：初始化内置策略
- `../bootstrap/init_v10_equity.py`：初始化 v10 权益快照数据

## 巡检 / 验证

- `../checks/check_db_data.py`：综合性数据库数据检查
- `../checks/check_filter_logic.py`：过滤逻辑检查
- `../checks/check_obs_data.py`：观测数据检查
- `../checks/check_schema.py`：数据库结构检查
- `../checks/check_scores.py`：评分检查
- `../checks/verify_dashboard_data.py`：看板数据验证

## 诊断 / 修复 / 工具

- `../diagnostics/diag_data_flow.py`：数据流排障
- `../diagnostics/debug_plans.py`：交易计划调试
- `../maintenance/fix_copilot_schema.py`：Copilot 结构修复
- `../maintenance/fix_order_book_stuck.py`：订单簿卡死修复
- `../maintenance/force_daily_cycle.py`：强制日循环
- `../maintenance/clean_duplicate_signals.py`：清理重复信号
- `../maintenance/clear_hk_name_cache.py`：清理港股名称缓存
- `../performance/benchmark_p95.py`：P95 性能基准测试
- `../performance/test_yf.py`：Yahoo Finance 连接测试

## 使用建议

- 如果你不确定脚本属于哪个版本，先看这里。
- 若脚本后来被确认绑定某一版本波次，再迁入对应版本归纳。
