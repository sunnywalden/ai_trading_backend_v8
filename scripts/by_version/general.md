# 通用脚本归纳

这些脚本不强绑定某个单一版本，适合作为长期运维、巡检、初始化或排障工具。

## 初始化 / 基础准备

- `../init_db.py`：初始化数据库基础结构
- `../init_strategies.py`：初始化内置策略
- `../init_v10_equity.py`：初始化 v10 权益快照数据

## 巡检 / 验证

- `../check_db_data.py`：综合性数据库数据检查
- `../check_filter_logic.py`：过滤逻辑检查
- `../check_obs_data.py`：观测数据检查
- `../check_schema.py`：数据库结构检查
- `../check_scores.py`：评分检查
- `../verify_dashboard_data.py`：看板数据验证

## 诊断 / 修复 / 工具

- `../diag_data_flow.py`：数据流排障
- `../debug_plans.py`：交易计划调试
- `../fix_copilot_schema.py`：Copilot 结构修复
- `../fix_order_book_stuck.py`：订单簿卡死修复
- `../force_daily_cycle.py`：强制日循环
- `../clean_duplicate_signals.py`：清理重复信号
- `../clear_hk_name_cache.py`：清理港股名称缓存
- `../benchmark_p95.py`：P95 性能基准测试
- `../test_yf.py`：Yahoo Finance 连接测试
- `../_run_archived.py`：归档脚本兼容运行入口

## 使用建议

- 如果你不确定脚本属于哪个版本，先看这里。
- 若脚本后来被确认绑定某一版本波次，再迁入对应版本归纳。
