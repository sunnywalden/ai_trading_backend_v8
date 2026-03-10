# 脚本目录说明

本目录目前同时承载 9 类内容：

1. **正式版本迁移脚本**：放在 `migrations/`
2. **历史一次性迁移脚本**：放在 `legacy_migrations/`
3. **初始化脚本**：放在 `bootstrap/`
4. **巡检 / 验证脚本**：放在 `checks/`
5. **诊断 / 排障脚本**：放在 `diagnostics/`
6. **修复 / 回填 / 运维脚本**：放在 `maintenance/`
7. **性能 / 外部依赖脚本**：放在 `performance/`
8. **SQL 配套文件**：放在 `sql/`
9. **按版本整理的检索索引**：放在 `by_version/`

> 当前目录已完成**物理重组**：根目录脚本已按用途迁入子目录，便于管理、维护与持续扩展。

## 📁 当前目录结构

- **[migrations/](migrations/)**：正式版本化迁移脚本（v3.1.1+）
- **[legacy_migrations/](legacy_migrations/)**：正式迁移体系建立前的历史脚本存档
- **[bootstrap/](bootstrap/)**：初始化脚本
- **[checks/](checks/)**：巡检 / 验证脚本
- **[diagnostics/](diagnostics/)**：诊断 / 排障脚本
- **[maintenance/](maintenance/)**：修复 / 回填 / 运维脚本
- **[performance/](performance/)**：性能 / 连通性脚本
- **[sql/](sql/)**：SQL 配套文件
- **[by_version/](by_version/)**：按版本归纳的脚本索引（推荐优先查看）
- **[archived/](archived/)**：按版本归档的历史现场脚本

## ✨ 当前根目录目标状态

`scripts/` 根目录现在应尽量只保留：

- 目录入口
- README
- 版本迁移体系目录
- 历史归档目录

不再堆放大量可执行脚本文件。

## 🧭 入口导航

如果你是第一次来这个目录，推荐直接从下面进入：

- **[by_version/README.md](by_version/README.md)**：总版本索引入口
- **[bootstrap/README.md](bootstrap/README.md)**：初始化脚本入口
- **[checks/README.md](checks/README.md)**：巡检 / 验证脚本入口
- **[diagnostics/README.md](diagnostics/README.md)**：诊断脚本入口
- **[maintenance/README.md](maintenance/README.md)**：修复 / 回填脚本入口
- **[performance/README.md](performance/README.md)**：性能脚本入口
- **[sql/README.md](sql/README.md)**：SQL 文件入口
- **[by_version/v3x.md](by_version/v3x.md)**：v3.x 相关脚本
- **[by_version/v9.md](by_version/v9.md)**：v9 相关脚本
- **[by_version/v10_2.md](by_version/v10_2.md)**：V10.2 相关脚本
- **[by_version/v10_3_x.md](by_version/v10_3_x.md)**：V10.3.x 相关脚本
- **[by_version/v10_4_x.md](by_version/v10_4_x.md)**：V10.4.x 相关脚本
- **[by_version/v10_5_x.md](by_version/v10_5_x.md)**：V10.5.x 相关脚本
- **[by_version/general.md](by_version/general.md)**：通用脚本归纳
- **[by_version/legacy.md](by_version/legacy.md)**：历史遗留迁移脚本归纳
- **[archived/README.md](archived/README.md)**：归档脚本入口

## 🔎 推荐查找顺序

当你要找某个版本相关脚本时，建议按下面顺序：

1. 先看 **[by_version/README.md](by_version/README.md)**
2. 再按版本进入对应分页面（如 `by_version/v10_4_x.md`）
3. 涉及数据库版本升级时，优先看 **[migrations/](migrations/)**
4. 涉及一次性历史迁移时，再看 **[legacy_migrations/](legacy_migrations/)**
5. 若脚本已归档，则进入 **[archived/README.md](archived/README.md)**
6. 若按用途查找，再进入 `bootstrap/`、`checks/`、`diagnostics/`、`maintenance/`、`performance/`、`sql/`

## 🧭 分类目录说明

### 初始化 / 启动准备

- 目录：**[bootstrap/](bootstrap/)**
- 说明页：**[bootstrap/README.md](bootstrap/README.md)**

### 巡检 / 校验 / 验证

- 目录：**[checks/](checks/)**
- 说明页：**[checks/README.md](checks/README.md)**

### 诊断 / 排障

- 目录：**[diagnostics/](diagnostics/)**
- 说明页：**[diagnostics/README.md](diagnostics/README.md)**

### 修复 / 回填 / 维护

- 目录：**[maintenance/](maintenance/)**
- 说明页：**[maintenance/README.md](maintenance/README.md)**

### 性能 / 外部依赖 / 杂项

- 目录：**[performance/](performance/)**
- 说明页：**[performance/README.md](performance/README.md)**

### SQL 配套文件

- 目录：**[sql/](sql/)**
- 说明页：**[sql/README.md](sql/README.md)**

### 现场临时脚本（已按版本归档）

以下脚本主要用于本地/线上现场排障，带 `_tmp_` 前缀。

- 实际脚本已迁入 **`archived/v10_4_3/`**
- 归档入口说明见 **[archived/README.md](archived/README.md)**
- 根目录不再保留 `_tmp_*` 包装脚本

已归档脚本：

- `_tmp_check_and_fix_three_failed.py`
- `_tmp_check_fsm_type_counts.py`
- `_tmp_check_s12.py`
- `_tmp_check_three_status.py`
- `_tmp_failed_three_detail.py`
- `_tmp_run_broker_sync.py`
- `_tmp_stage7_diagnose.py`
- `_tmp_stage7_evidence.py`
- `_tmp_system_monitor_inspect.py`

## 🗂️ 按版本归纳入口

- **[by_version/README.md](by_version/README.md)**：版本总索引

进一步可按版本进入：

- **[by_version/v3x.md](by_version/v3x.md)**
- **[by_version/v9.md](by_version/v9.md)**
- **[by_version/v10_2.md](by_version/v10_2.md)**
- **[by_version/v10_3_x.md](by_version/v10_3_x.md)**
- **[by_version/v10_4_x.md](by_version/v10_4_x.md)**
- **[by_version/general.md](by_version/general.md)**
- **[by_version/legacy.md](by_version/legacy.md)**

其中重点整理了：

- `v3.x` 基线迁移脚本
- `v9` 初始化脚本
- `v10.2` 迁移脚本
- `v10.3.x` 升级 / 验收 / 数据修复脚本
- `v10.4.x` 升级 / 验收 / 生命周期与监控上线辅助脚本
- `v10.5.x` 升级 / 执行画像回填 / 数据修复脚本

## ⚠️ 使用建议

1. **数据库版本升级优先使用 `migrations/`**，不要拿根目录临时脚本替代正式迁移。
2. 运行迁移、批量修复、回填脚本前，**先备份数据库**。
3. `_tmp_*` 脚本已迁入 `archived/`；如需追溯原始内容，优先查看归档目录。
4. 如果某脚本绑定某个版本波次，优先从 `by_version/README.md` 查询其上下文，再执行。
