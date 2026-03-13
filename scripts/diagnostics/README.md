# diagnostics

诊断、排障、现场分析类脚本。

## 典型用途

- 数据流链路排障
- 生命周期问题诊断
- Stage7 / post-trade 问题定位
- 计划调试

本目录下脚本可直接通过 `python scripts/diagnostics/<script>.py` 运行。

## 当前常用脚本

- `diag_signal_origin_pipeline.py`：统计最近窗口内 REAL / SYNTHETIC / BACKFILL 信号分布、Watchtower / Validation / Intent 阻塞原因，以及 pending / executed 来源结构。
