# checks

巡检、验收、验证类脚本。

## 典型用途

- 数据校验
- 结构检查
- 生命周期可见性验证
- 版本验收

本目录下脚本可直接通过 `python scripts/checks/<script>.py` 运行。

## 新增脚本

- `check_live_safety_self_check.py`
	- 用途：检查 `Live Safety` freshness 矩阵与关键健康检查
	- 默认行为：执行一次技术指标刷新任务，然后输出 freshness / health 摘要
	- 常用示例：
		- `python scripts/checks/check_live_safety_self_check.py`
		- `python scripts/checks/check_live_safety_self_check.py --json`
		- `python scripts/checks/check_live_safety_self_check.py --skip-refresh-job`
