# maintenance

修复、回填、清理、同步、上线辅助类脚本。

## 典型用途

- 生命周期修复
- 券商撤单同步
- 日志/FSM 回填
- 数据维度修复
- 清理和推进卡住计划

本目录下脚本可直接通过 `python scripts/maintenance/<script>.py` 运行。

## V10.5.3 新增

- `../migrations/backfill_execution_policy_profiles.py`：从历史 `execution_quality_log` 幂等回填 `execution_policy_profiles`。
- `repair_execution_policy_profiles.py`：校验并修复 `execution_policy_profiles` 的 stale / orphan / missing / duplicate 数据。
- `execution_policy_profile_common.py`：执行画像回填/修复共用聚合逻辑（供迁移脚本与修复脚本复用）。

## V10.5.4 / 生产信号来源治理

- `cleanup_synthetic_pending_signals.py`：默认 dry-run，安全过期旧的 synthetic pending 信号（仅限 GENERATED / VALIDATED，`--include-queued` 可选纳入 오래 QUEUED）。
