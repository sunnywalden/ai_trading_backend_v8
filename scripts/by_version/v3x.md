# v3.x 脚本归纳

适用于早期正式版本迁移基线，重点是数据库结构升级、验证与回滚。

## 正式迁移脚本

- `../migrations/upgrade_to_v3.1.1.py`：升级到 v3.1.1
- `../migrations/verify_v3.1.1.py`：验证 v3.1.1 结构
- `../migrations/rollback_from_v3.1.1.py`：从 v3.1.1 回滚
- `../migrations/upgrade_to_v3.2.1.py`：升级到 v3.2.1
- `../migrations/verify_v3.2.1.py`：验证 v3.2.1 结构
- `../migrations/version_manager.py`：版本记录与状态管理

## 使用建议

1. 这组脚本优先用于数据库版本升级流程。
2. 涉及回滚时，先备份，再执行回滚。
3. 若要确认执行顺序，配合 `../migrations/README.md`、`WORKFLOW.md`、`QUICK_REFERENCE.md` 一起看。
