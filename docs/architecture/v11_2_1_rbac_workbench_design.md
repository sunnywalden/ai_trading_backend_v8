# V11.2.1 RBAC & Role Workbench Design

## 目标

V11.2.1 将交易控制台拆分为四类角色工作台：`Researcher`、`Trader`、`Supervisor`、`Administrator`，并引入后端真源 RBAC，避免此前“前端只看是否登录、后端几乎全员管理员”的权限漂移。

## 后端变更

### RBAC 数据模型

新增表：

- `roles`
- `permissions`
- `users`
- `user_role_bindings`
- `role_permission_grants`
- `authorization_audit_logs`

### 认证与授权

- `/api/v1/login` 在 `RBAC_V1121_ENABLED=true` 时优先走 RBAC 用户认证；未启用时保持原单管理员兼容模式。
- JWT payload 新增：`role`、`permissions`、`permissions_version`、`display_name`。
- 新增：
  - `GET /api/v1/auth/me`
  - `GET /api/v1/auth/permissions`
- 关键路由通过 `require_permission(...)` / `require_any_role(...)` 收口。

### 角色首页读模型

新增只读聚合接口：

- `GET /api/v1/research/home`
- `GET /api/v1/trading/home`
- `GET /api/v1/executive/summary`
- `GET /api/v1/executive/risk-report`
- `GET /api/v1/executive/performance-report`
- `GET /api/v1/admin/overview`

### 管理接口

新增：

- `GET/POST/PATCH /api/v1/admin/users`
- `POST /api/v1/admin/users/{user_id}/roles`
- `GET/POST/PATCH /api/v1/admin/roles`
- `GET /api/v1/admin/permissions`
- `GET /api/v1/admin/audit/authz`

### 验收后补强（Follow-up Hardening）

- `GET /api/v1/auth/me` 与登录响应现在同时返回前端消费的 `feature_flags`，让角色首页、导航裁剪、按钮权限和报表/管理台灰度与后端配置保持同源。
- `users.must_change_password` 字段用于承载种子账号和管理员重置密码后的首登改密要求；新增 `POST /api/v1/auth/change-password` 完成自助改密闭环。
- `admin_overview` 读模型与前端管理台已补齐“权限目录”入口，不再只有用户/角色/审计三件套。

### 发布脚本

- 迁移：`scripts/migrations/upgrade_to_v11_2_1.py`
- 种子用户：`scripts/bootstrap/init_rbac_seed_users.py`

## 前端变更

### 新增角色首页

- `/research`
- `/trading`
- `/executive`
- `/admin`

### 新增管理与报表页

- `/admin/users`
- `/admin/roles`
- `/admin/audit`
- `/reports/executive`
- `/reports/risk`
- `/reports/performance`
- `/forbidden`

### 统一鉴权机制

- Pinia `auth` store 负责角色、权限、首页路径与路由可达性判断。
- `PermissionGuard` / `PermissionButton` 统一按钮和内容片段的权限控制。
- `src/router/index.ts` 中的 `resolveRouteAccess()` 将路径与角色规则集中管理，菜单过滤和守卫复用同一份规则。

## 环境变量

新增模板变量：

- `SEED_RESEARCHER_PASSWORD`
- `SEED_TRADER_PASSWORD`
- `SEED_SUPERVISOR_PASSWORD`
- `SEED_ADMIN_PASSWORD`
- `RBAC_V1121_ENABLED`
- `ROLE_HOME_V1121_ENABLED`
- `ROLE_NAV_GATING_V1121_ENABLED`
- `ROLE_ACTION_GATING_V1121_ENABLED`
- `EXECUTIVE_REPORTS_V1121_ENABLED`
- `ADMIN_CONSOLE_V1121_ENABLED`

## 灰度建议

1. 先执行迁移脚本。
2. 设置四个种子账号密码并初始化种子用户。
3. 打开 `RBAC_V1121_ENABLED`，验证 `/api/v1/auth/me` 与四类首页。
4. 再逐步打开前端 `ROLE_HOME` / `ROLE_NAV_GATING` / `ROLE_ACTION_GATING` 相关功能位。
5. 观察 `authorization_audit_logs` 中的 `DENY` 记录，确认无误后扩大使用范围。
