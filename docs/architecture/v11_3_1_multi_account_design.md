# V11.3.1 Multi-Account & Account-Scoped Data Governance Design

> 状态：规划定稿 | 版本：v1.0 | 日期：2026-03-15  
> 完整规划：[docs/archived/v11/v11.3/RELEASE_PLAN_V11.3.1.md](../../archived/v11/v11.3/RELEASE_PLAN_V11.3.1.md)  
> 前序版本：[V11.2.1 RBAC & Role Workbench Design](v11_2_1_rbac_workbench_design.md)

## 目标

V11.3.1 将系统从"绑定单个 Tiger 账户"升级为支持**同时注册多个 Tiger 经纪账户、按账户隔离数据、按用户配置账户访问权限**的多账户多操作员平台。

## 数据模型变更

新增三张表：

- `broker_accounts` — 经纪账户注册表（账户 ID、别名、类型、市场、活跃状态）
- `broker_account_credentials` — 凭证存储（AES-256-GCM 加密后的 Tiger 私钥，不出现在响应中）
- `user_broker_account_grants` — 用户账户授权表（`user_id`、`broker_account_id`、`grant_level`）

授权级别 `grant_level`：`VIEW` / `ANALYZE` / `OPERATE` / `ADMIN`

有效访问模型（两层合并）：

```
功能权限（V11.2.1 RBAC 角色）∩ 数据范围（V11.3.1 账户授权）= 最终有效操作
```

## 后端变更

### BrokerAccountRegistry

新增 `app/broker/broker_account_registry.py`：

- 按 `account_id` 路由 `TigerOptionClient` 实例（进程级缓存字典）
- 进程启动时从 DB 预热所有活跃账户连接
- `factory.py` 保持接口兼容，内部转发到 Registry
- `BROKER_ACCOUNT_REGISTRY_V1131_ENABLED=False` 时退回原有 singleton 行为

### UserContext 扩展

```python
# app/core/auth_context.py
@dataclass(slots=True)
class UserContext:
    # ... 原有字段 ...
    accessible_account_ids: list[str] = field(default_factory=list)
    default_account_id: str | None = None
    account_grants: dict[str, str] = field(default_factory=dict)  # account_id → grant_level
```

`rbac_service.build_user_context()` 同步查询 `user_broker_account_grants` 回填这三个字段。

### 账户上下文依赖注入

新增 `app/core/account_context.py`：

- `get_current_account_id` — 按优先级解析请求中的账户 ID（Header → Query → 用户默认 → fallback）
- `require_account_access(min_level)` — 校验用户对目标账户有足够的 grant_level

### 新增管理 API

```
GET/POST/PATCH/DELETE  /api/v1/admin/broker-accounts
POST                   /api/v1/admin/broker-accounts/{id}/credentials
GET/POST/PATCH/DELETE  /api/v1/admin/users/{user_id}/account-grants
GET                    /api/v1/auth/my-accounts
```

所有授权变更写入 `authorization_audit_logs`（沿用 V11.2.1 审计机制）。

## 前端变更

### 新增页面

- `AdminBrokerAccountsPage.vue` — 账户注册与凭证管理（路由：`/admin/broker-accounts`）
- `AdminUserAccountGrantsPage.vue` — 用户账户授权管理（嵌入 AdminUsersPage 用户详情）

### WorkbenchShell 扩展

当 `accessibleAccounts.length > 1` 时，在顶部导航栏展示账户选择器下拉。切换后：
1. `auth` store 更新 `currentAccountId`
2. `client.ts` 拦截器在后续请求中注入 `X-Account-ID` 请求头
3. 当前页面数据刷新

### `auth` Store 扩展

新增字段：`accessibleAccounts`、`currentAccountId`、`accountGrants`  
新增 getter：`canOperateAccount(id)`、`canViewAccount(id)`

## 环境变量

新增模板变量：

- `MULTI_ACCOUNT_V1131_ENABLED`
- `BROKER_ACCOUNT_REGISTRY_V1131_ENABLED`
- `ACCOUNT_DATA_ISOLATION_V1131_ENABLED`
- `ACCOUNT_ADMIN_UI_V1131_ENABLED`
- `BROKER_CREDENTIAL_ENCRYPTION_KEY`（AES-256-GCM 密钥，不得提交 Git）

## 灰度建议

1. 执行迁移脚本，创建三张新表并回补默认账户 + 用户授权。
2. 打开 `MULTI_ACCOUNT_V1131_ENABLED` 和 `BROKER_ACCOUNT_REGISTRY_V1131_ENABLED`，验证默认账户连接正常。
3. 打开 `ACCOUNT_ADMIN_UI_V1131_ENABLED`，管理员通过后台录入额外账户和授权配置。
4. 管理员完成账户授权调整（特别是 M0 迁移时补写的临时宽泛授权需要收紧）。
5. 打开 `ACCOUNT_DATA_ISOLATION_V1131_ENABLED`，验证数据隔离过滤正确，审计日志无异常。

## 发布脚本

- 迁移：`scripts/migrations/upgrade_to_v11_3_1.py`
- 验收：`scripts/checks/_acceptance_v11_3_1.py`
