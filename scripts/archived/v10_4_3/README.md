# V10.4.3 现场临时排障脚本归档

本目录存放最近一轮 **V10.4.3 生命周期 / 系统监控 / 对账** 排障过程中产生的临时脚本。

## 说明

- 这些脚本主要用于现场排障、证据提取、一次性数据核验。
- 当前以归档目录作为唯一保留位置，根目录不再保留 `_tmp_*` 包装脚本。
- 如需执行，请直接使用 `python scripts/archived/v10_4_3/<script>.py`。

## 脚本列表

- `_tmp_system_monitor_inspect.py`
- `_tmp_run_broker_sync.py`
- `_tmp_stage7_diagnose.py`
- `_tmp_stage7_evidence.py`
- `_tmp_failed_three_detail.py`
- `_tmp_check_three_status.py`
- `_tmp_check_and_fix_three_failed.py`
- `_tmp_check_s12.py`
- `_tmp_check_fsm_type_counts.py`
