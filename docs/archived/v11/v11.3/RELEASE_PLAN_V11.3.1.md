# V11.3.1 Release Plan — Multi-Account Support & Account-Scoped Data Governance

> AI量化交易闭环系统 — V11.3.1 规划说明  
> 文档版本：v1.0（终稿） | 日期：2026-03-15 | 状态：规划定稿  
> 当前代码基线：V11.2.1 RBAC & Role Workbench  
> 核心命题：**从"单一 Tiger 账户 + 全员同视角"演进为"多账户注册 + 用户按账户粒度授权"的多账户多操作员治理平台。**

---

## 0. 版本定位

### 0.1 一句话定义

V11.3.1 是一次 **Multi-Account Support & Account-Scoped Data Governance** 升级：

> 让系统从"绑定单个 Tiger 账户、数据对所有用户等同可见"的单账户模式，演进为支持**同时接入多个 Tiger 经纪账户、每账户数据独立隔离、每用户按账户粒度配置数据访问权限**的多账户治理体系。

### 0.2 产品背景与使用场景

当前平台的定位是"个人美港股智能交易平台"，但随着平台能力成熟，出现了明确的多账户需求场景：

| 场景 | 描述 | 当前痛点 |
| ---- | ---- | -------- |
| 主号 + 模拟号并行 | 同一用户同时运行 Live 账户和 Paper Trading 账户 | 只能通过 Paper 内置模拟，无法接入独立 Tiger Paper 账户 |
| 家庭账户组 | 夫妻或家庭成员各持不同 Tiger 账户，共用同一套平台 | 无法区分"谁能看谁的账户" |
| 小型研究团队 | 研究员、交易员各有专属账户，账户间数据不应互相暴露 | 当前角色权限管不到账户维度 |
| 分账户策略隔离 | 同一人用不同账户跑不同策略，避免交叉影响 | RiskGate 无法按账户独立运行 |

V11.3.1 的目标不是 SaaS 多租户，而是"**多账户多操作员**"支持——小规模团队共用一套部署。

### 0.3 版本命题与 V11.2.1 的关系

V11.2.1 回答了"谁能做什么"（角色 + 功能权限），V11.3.1 回答"谁能看哪些账户的数据"。

```
V11.2.1：用户 → 角色 → 功能权限（能干什么、能操作哪些模块）
V11.3.1：用户 → 账户授权 → 账户数据范围（能看/能操作哪个经纪账户的数据）

V11.3.1 最终合并：
  用户 ─→ 角色（V11.2.1）─→ 功能权限判断
       └→ 账户授权（V11.3.1）─→ 数据范围判断
  有效访问 = 功能权限 ∩ 账户数据范围
```

**硬前提**：V11.3.1 要求 `RBAC_V1121_ENABLED=True`（V11.2.1 RBAC 必须已启用）。

### 0.4 本版本不在范围内

1. **跨账户聚合风险计算**：RiskGate、CapacityArbiter、VaR 计算必须保持**按经纪账户独立**，不做跨账户汇总风险分析（可以在后续版本作为高级功能）。
2. **SaaS 完整多租户隔离**：此版本不引入独立的 DB schema 隔离，同一表通过 `broker_account_id` 外键区分数据。
3. **外部用户自助注册和账户申请**：账户和授权均由管理员后台配置，不开放自助流程。
4. **跨平台账户同步**：不自动同步外部账户配置，账户需管理员手动录入。

### 0.5 V11.3.1 不可妥协的边界

1. **RiskGate 和交易主链必须按账户隔离**：多账户接入不能导致跨账户头寸合并影响风控计算。
2. **功能权限仍以 V11.2.1 RBAC 为准**：账户授权是数据维度，不是功能维度替代。
3. **账户凭证必须安全存储**：Tiger 私钥等凭证不得以明文暴露在 API 响应或日志中。
4. **向后兼容**：V11.3.1 关闭时（`MULTI_ACCOUNT_V1131_ENABLED=False`），行为退回 V11.2.1 单账户模式。
5. **管理员授权行为全量审计**：所有账户授权变更必须写入 `authorization_audit_logs`。

---

## 1. 顶层目标

### 1.1 版本总目标

V11.3.1 完成以下四件事：

1. **建立经纪账户注册表**：系统可同时接入和管理多个 Tiger 经纪账户；  
2. **多账户 Tiger 客户端路由**：按 `broker_account_id` 路由到对应的 Tiger 客户端实例；  
3. **账户级数据隔离**：API 查询和数据服务按当前用户的账户访问权限过滤结果；  
4. **管理员可配置账户授权**：管理员可通过后台页面管理账户注册、用户账户授权关系。

### 1.2 五条设计原则

| 原则 | 含义 |
| ---- | ---- |
| 账户独立性 | 每个经纪账户的交易、头寸、风险数据相互隔离 |
| 最小数据授权 | 用户只能看到被明确授权账户的数据 |
| 角色与账户正交 | 功能权限（V11.2.1）和数据范围（V11.3.1）独立叠加 |
| 凭证安全优先 | Tiger 私钥加密存储，不出现在 API 响应和日志中 |
| 向后兼容 | 功能关闭时行为降级为 V11.2.1 单账户模式 |

### 1.3 成功标准

| 维度 | 当前问题 | V11.3.1 目标 | 验收方式 |
| ---- | -------- | ------------ | -------- |
| Tiger 接入 | 仅支持单账户全局单例 | 支持同时注册 N 个经纪账户并按需路由 | API 测试 + 集成测试 |
| 数据查看 | 所有用户看全量数据 | 用户只看授权账户数据 | 账户过滤验收 |
| 授权配置 | 无账户维度权限 | 管理员可为用户配置账户访问权限 | 管理后台验收 |
| 凭证安全 | 私钥路径明文配置 | 凭证加密存储，API 不泄露原始凭证 | 安全验收 |
| 审计覆盖 | 无账户授权审计 | 账户创建、授权变更全量写入审计日志 | 审计日志验收 |
| RiskGate 隔离 | N/A（单账户） | RiskGate 调用携带 `broker_account_id`，风控计算按账户独立 | 风控隔离测试 |

---

## 2. 核心概念定义

### 2.1 概念层次

```
BrokerAccount（经纪账户）
    ↑ 注册在 BrokerAccountRegistry
    ↑ 每个账户对应一套 Tiger 认证凭证和一个 TigerOptionClient 实例
    ↑ 已有业务表中的 account_id 字段对应此概念

UserBrokerAccountGrant（用户账户授权）
    ↑ 表达"用户 X 对经纪账户 Y 拥有何种访问级别"
    ↑ grant_level: VIEW / ANALYZE / OPERATE / ADMIN

UserContext（已有，V11.2.1）
    ↑ 扩展：新增 accessible_account_ids 和 default_account_id 字段
```

> **重要**：V11.3.1 不引入独立的"租户（Tenant）"层级抽象。"账户"既是认证凭证单元，也是数据隔离单元。如未来需要账户分组管理，可在 V11.4.x 引入 AccountGroup。

### 2.2 授权级别（grant_level）

| 级别 | 名称 | 含义 |
| ---- | ---- | ---- |
| `VIEW` | 摘要查看 | 只能看该账户的聚合摘要数据（净值曲线、总盈亏） |
| `ANALYZE` | 完整读取 | 可查看账户全量数据（交易记录、持仓明细、信号历史） |
| `OPERATE` | 操作权限 | 在完整读取基础上，可发起交易动作（受 RiskGate 约束） |
| `ADMIN` | 账户管理 | 可管理账户配置、凭证更新、账户停启（仅 Administrator 角色） |

### 2.3 有效访问合并规则

```
有效功能权限 = RBAC 角色权限（V11.2.1）
有效数据范围 = 用户被授权的账户集合（V11.3.1）

有效操作 = 功能权限 AND 数据范围内对应账户的 grant_level
```

示例：
- Researcher + ANALYZE 授权 → 可研究分析该账户数据，不可发起交易（Researcher 无交易功能权限）  
- Trader + VIEW 授权 → 只能看摘要，不能发起交易（grant_level < OPERATE）  
- Trader + OPERATE 授权 → 可为该账户发起交易执行流程  
- Supervisor + ANALYZE 授权 → 可查阅账户全量报表  
- Administrator + ADMIN 授权 → 可管理账户配置  

---

## 3. 系统设计

### 3.1 数据模型变更

#### 新增表：`broker_accounts`

```sql
CREATE TABLE broker_accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    VARCHAR(64) NOT NULL UNIQUE,   -- Tiger 账户号（对应现有 account_id 字段）
    display_name  VARCHAR(128),                  -- 账户别名（如"主力账户"）
    account_type  VARCHAR(32) DEFAULT 'LIVE',    -- LIVE / PAPER / DEMO
    market        VARCHAR(16) DEFAULT 'US',      -- US / HK / BOTH
    tiger_id      VARCHAR(64),                   -- Tiger 开发者 ID
    credential_ref VARCHAR(256),                 -- 私钥凭证引用（加密存储引用 key，不存原文）
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### 新增表：`user_broker_account_grants`

```sql
CREATE TABLE user_broker_account_grants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,       -- FK → users.id
    broker_account_id   INTEGER NOT NULL,       -- FK → broker_accounts.id
    grant_level         VARCHAR(16) NOT NULL,   -- VIEW / ANALYZE / OPERATE / ADMIN
    granted_by          INTEGER,                -- FK → users.id（授权操作人）
    granted_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    revoked_at          DATETIME,               -- 软删除
    is_active           BOOLEAN DEFAULT TRUE,
    UNIQUE (user_id, broker_account_id)
);
```

#### 新增表：`broker_account_credentials`

```sql
CREATE TABLE broker_account_credentials (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_account_id   INTEGER NOT NULL UNIQUE,  -- FK → broker_accounts.id
    tiger_id            VARCHAR(64) NOT NULL,
    private_key_enc     TEXT NOT NULL,            -- AES-256 加密后的私钥内容
    key_fingerprint     VARCHAR(64),              -- 私钥指纹（用于验证不出原文）
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

> **凭证安全说明**：  
> - `private_key_enc` 使用 AES-256-GCM 加密，加密密钥来自环境变量 `BROKER_CREDENTIAL_ENCRYPTION_KEY`；  
> - API 响应中只返回 `key_fingerprint`，原始私钥和加密后内容不出现在任何响应体、日志和审计中；  
> - 如果部署环境已有 KMS（如 AWS KMS），可将 `BROKER_CREDENTIAL_ENCRYPTION_KEY` 替换为 KMS 密钥引用。

#### `UserContext` 扩展（`app/core/auth_context.py`）

```python
@dataclass(slots=True)
class UserContext:
    # ... 原有字段 ...
    accessible_account_ids: list[str] = field(default_factory=list)
    default_account_id: str | None = None
    account_grants: dict[str, str] = field(default_factory=dict)  # account_id → grant_level
```

### 3.2 Tiger 客户端注册表（BrokerAccountRegistry）

#### 当前问题

`app/broker/factory.py` 维护全局单例 `_broker_instance`，绑定 `settings.TIGER_ACCOUNT` 单账户。

#### 目标设计

新增 `app/broker/broker_account_registry.py`：

```python
class BrokerAccountRegistry:
    """按 account_id 路由 TigerOptionClient 实例（进程级缓存）"""

    _instances: dict[str, TigerOptionClient] = {}

    @classmethod
    async def get(cls, account_id: str) -> TigerOptionClient:
        """获取或创建指定账户的 Tiger 客户端。"""
        ...

    @classmethod
    async def register(cls, account: BrokerAccount, credentials: BrokerAccountCredentials) -> None:
        """注册一个新账户并预热连接。"""
        ...

    @classmethod
    async def deregister(cls, account_id: str) -> None:
        """注销账户，关闭并清理连接。"""
        ...

    @classmethod
    async def list_active(cls) -> list[str]:
        """列出所有已注册的活跃账户 ID。"""
        ...
```

#### 向后兼容策略

`make_option_broker_client()` 和 `get_tiger_client()` 保持兼容签名，内部转发到 `BrokerAccountRegistry.get(settings.TIGER_ACCOUNT)`。

当 `MULTI_ACCOUNT_V1131_ENABLED=False` 时，`BrokerAccountRegistry` 仍只实例化默认账户。

### 3.3 认证与 JWT 变更

#### JWT Payload 扩展

```json
{
  "sub": "alice",
  "role": "TRADER",
  "permissions": ["trade.execute", "position.view"],
  "permissions_version": 3,
  "accessible_account_ids": ["21272246230273657", "21272246230273658"],
  "default_account_id": "21272246230273657",
  "account_grants": {
    "21272246230273657": "OPERATE",
    "21272246230273658": "ANALYZE"
  },
  "exp": 1742000000
}
```

> **注意**：JWT payload 不包含凭证信息，只包含账户 ID 列表和 grant_level。账户 ID 本身不是敏感信息（类似于数据库主键）。

#### UserContext 构建路径

```
RBAC 认证（V11.2.1）
  └→ rbac_service.build_user_context(user_id)
       └→ [V11.3.1 新增] 查询 user_broker_account_grants → 填充 accessible_account_ids + account_grants
```

#### API 请求账户解析

新增 `app/core/account_context.py`：

```python
async def get_current_account_id(
    request: Request,
    user_ctx: UserContext = Depends(require_auth),
) -> str:
    """
    从以下来源按优先级解析当前请求的 account_id：
    1. 请求头 X-Account-ID
    2. 查询参数 ?account_id=...
    3. 用户默认账户 (user_ctx.default_account_id)
    4. settings.TIGER_ACCOUNT（向后兼容 fallback）

    解析后验证用户对该账户是否有访问权限（否则抛 403）。
    """
    ...

def require_account_access(min_level: str = "VIEW"):
    """依赖注入工厂：要求当前账户存在且用户有 >= min_level 的访问权限。"""
    ...
```

### 3.4 数据隔离层

#### 存量业务表中已有 `account_id` 的表

以下业务表**已经**有 `account_id` 字段，V11.3.1 在服务层添加 `WHERE account_id IN (accessible_account_ids)` 过滤：

- `trading_signals`
- `positions`
- `autonomous_execution_intent`
- `signal_quality_audit_logs`
- `capacity_decision_audit_log`
- `trade_attribution`
- 等...（详见 migration script 扫描清单）

#### 共享类表（不隔离）

以下表属于系统级共享配置，不按账户隔离：

- `strategies`、`backtest_runs`（策略库全局共享）
- `roles`、`users`、`permissions`（RBAC 全局）
- `regime_snapshots`、`event_calendar`（市场数据全局）

#### 隔离执行层接口

新增规范依赖：

```python
# 需要账户访问权限的路由依赖注入示例
@router.get("/positions")
async def list_positions(
    account_id: str = Depends(get_current_account_id),
    user_ctx: UserContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    # account_id 已通过 require_account_access 校验
    return await position_service.list_by_account(db, account_id)
```

### 3.5 后端 API 变更

#### 新增账户管理 API（管理员专属）

```
# 经纪账户管理
GET    /api/v1/admin/broker-accounts          -- 列出所有注册账户
POST   /api/v1/admin/broker-accounts          -- 注册新账户
PATCH  /api/v1/admin/broker-accounts/{id}     -- 更新账户信息
POST   /api/v1/admin/broker-accounts/{id}/credentials  -- 更新/上传凭证
DELETE /api/v1/admin/broker-accounts/{id}     -- 停用账户

# 用户账户授权管理
GET    /api/v1/admin/users/{user_id}/account-grants         -- 查看某用户的账户授权
POST   /api/v1/admin/users/{user_id}/account-grants         -- 新增账户授权
PATCH  /api/v1/admin/users/{user_id}/account-grants/{id}    -- 修改授权级别
DELETE /api/v1/admin/users/{user_id}/account-grants/{id}    -- 撤销授权

# 当前用户可用账户（所有角色均可调用）
GET    /api/v1/auth/my-accounts                             -- 返回当前用户可访问的账户列表
```

#### 存量 API 向后兼容策略

- 当 `ACCOUNT_DATA_ISOLATION_V1131_ENABLED=False` 时，存量 API 的 `account_id` 参数降级为 `settings.TIGER_ACCOUNT`，行为与 V11.2.1 相同。
- 当隔离开启时，如果请求未携带 `account_id`，自动使用 `user_ctx.default_account_id`。

---

## 4. 前端规划

### 4.1 目标

让管理员可以在前端完成账户注册和用户账户授权配置，让普通用户可以切换当前操作账户。

### 4.2 新增页面

#### `AdminBrokerAccountsPage.vue`

- 功能：经纪账户 CRUD（列表、新增、编辑、停用）；凭证上传（PEM 文件，不回显内容，只验证指纹）
- 路由：`/admin/broker-accounts`
- 权限：`Administrator` 角色 + `admin.broker_account.manage` 权限
- 布局：沿用现有 AdminUsersPage 风格，卡片列表 + 侧边表单

#### `AdminUserAccountGrantsPage.vue`

- 功能：在用户详情侧边栏中增加"账户授权"标签页（复用 AdminUsersPage 基础结构）
- 路由：`/admin/users/{id}/account-grants`（嵌入用户详情展示）
- 权限：`admin.user.manage`
- 布局：账户列表 + grant_level 下拉框 + 授权/撤销按钮

#### `AdminHomePage.vue` 扩展

在管理员概览页增加"账户健康"卡片：
- 注册账户数量及连接状态（正常/断开/凭证过期）

### 4.3 WorkbenchShell 账户选择器

当用户有多个可访问账户时，在顶部导航栏（WorkbenchShell）展示账户选择器：

```
[ 主力账户 (US) ↓ ]   当前操作账户下拉；选择后刷新当前页数据
```

- 仅当 `accessible_account_ids.length > 1` 时显示
- 切换后写入 `auth` store 的 `currentAccountId`
- 发送 `X-Account-ID` 请求头到所有后续 API 请求

### 4.4 Pinia `auth` store 扩展

```typescript
// src/stores/auth.ts 新增字段
interface AuthState {
  // 原有...
  accessibleAccounts: AccountSummary[]  // 用户可访问账户列表
  currentAccountId: string | null       // 当前选中账户 ID
  accountGrants: Record<string, string> // account_id → grant_level
}

// 新增 getter
const canOperateAccount = (accountId: string) => {
  const level = accountGrants[accountId]
  return ['OPERATE', 'ADMIN'].includes(level)
}

const canViewAccount = (accountId: string) => {
  return accountId in accountGrants
}
```

### 4.5 API 服务扩展

新增 `src/api/adminBrokerAccountService.ts`：

```typescript
// CRUD for broker accounts
export const listBrokerAccounts = () => client.get(...)
export const createBrokerAccount = (payload) => client.post(...)
export const updateBrokerAccount = (id, payload) => client.patch(...)
export const uploadAccountCredentials = (id, formData) => client.post(...)
export const listUserAccountGrants = (userId) => client.get(...)
export const grantAccountAccess = (userId, payload) => client.post(...)
export const revokeAccountAccess = (userId, grantId) => client.delete(...)
```

---

## 5. 数据迁移与发布脚本

### 5.1 迁移脚本（`scripts/migrations/upgrade_to_v11_3_1.py`）

迁移步骤：

1. 创建 `broker_accounts` 表，插入一条默认账户（来自 `settings.TIGER_ACCOUNT`）；
2. 创建 `broker_account_credentials` 表（空，等待管理员手动录入凭证）；
3. 创建 `user_broker_account_grants` 表；
4. 为所有现有 `Administrator` 角色用户，对默认账户授予 `ADMIN` 级别授权；
5. 为所有其他活跃用户，对默认账户授予 `ANALYZE` 级别授权（临时值，管理员应在上线后审查并调整）；
6. 添加环境变量模板：`BROKER_CREDENTIAL_ENCRYPTION_KEY`（空值模板，提醒管理员填写）。

> **注意**：迁移脚本会为所有现有用户补写账户授权，这是保持向后兼容的必要步骤。管理员需要在上线后主动审查并收紧授权范围。

### 5.2 验证脚本（`scripts/checks/_acceptance_v11_3_1.py`）

验收检查项：

1. `broker_accounts` 表存在且含默认账户记录；
2. `user_broker_account_grants` 表存在且 migrated_users_count > 0；
3. `BrokerAccountRegistry` 可以用默认账户 ID 获取 TigerOptionClient；
4. `UserContext` 包含 `accessible_account_ids` 字段；
5. `/api/v1/admin/broker-accounts` 返回 200（需 Administrator 账户）；
6. `/api/v1/auth/my-accounts` 返回当前用户有权访问的账户列表；
7. 数据隔离：使用 `account_id=X` 查询 positions 时，只返回 X 账户的数据。

---

## 6. 环境变量

新增以下模板变量（`.env.example`）：

```env
# V11.3.1 Multi-Account Support

# 主开关：是否启用多账户支持（默认关闭，V11.2.1 行为）
MULTI_ACCOUNT_V1131_ENABLED=false

# 是否启用经纪账户客户端注册表（BrokerAccountRegistry 代替 factory singleton）
BROKER_ACCOUNT_REGISTRY_V1131_ENABLED=false

# 是否启用账户级数据隔离（开启后 API 查询结果按授权账户过滤）
ACCOUNT_DATA_ISOLATION_V1131_ENABLED=false

# 是否启用账户管理 Admin UI
ACCOUNT_ADMIN_UI_V1131_ENABLED=false

# 账户凭证加密密钥（AES-256-GCM，32字节 Base64 编码）
# 必须在启用 MULTI_ACCOUNT_V1131_ENABLED 前设置
BROKER_CREDENTIAL_ENCRYPTION_KEY=
```

### 灰度开关顺序

```
第一步：MULTI_ACCOUNT_V1131_ENABLED=true
        → 激活账户注册表和管理 API，但不隔离数据

第二步：BROKER_ACCOUNT_REGISTRY_V1131_ENABLED=true
        → BrokerAccountRegistry 替代 factory singleton
        → 验证默认账户连接正常

第三步：ACCOUNT_ADMIN_UI_V1131_ENABLED=true
        → 开放管理员 UI，录入账户信息和额外凭证

第四步：（管理员操作）在后台为用户配置账户授权

第五步：ACCOUNT_DATA_ISOLATION_V1131_ENABLED=true
        → 启用数据隔离过滤，验证每个用户只能看授权账户数据
```

---

## 7. 后端里程碑

### M0 — 基础设施（数据层）

- 新增 `broker_accounts`、`user_broker_account_grants`、`broker_account_credentials` 三张表
- 新增 ORM 模型：`BrokerAccount`、`UserBrokerAccountGrant`、`BrokerAccountCredential`
- 新增 Pydantic schemas
- 编写迁移脚本，含默认账户回补

**产出**：DB 结构完整，迁移脚本可跑，单元测试覆盖 ORM 模型

### M1 — Tiger 客户端注册表

- 新增 `app/broker/broker_account_registry.py`：`BrokerAccountRegistry` 类
- 凭证加解密工具：`app/core/credential_store.py`（AES-256-GCM）
- 兼容包装：`factory.py` 保持接口不变，内部转发到 Registry
- 当 `BROKER_ACCOUNT_REGISTRY_V1131_ENABLED=False` 时退回原有 singleton

**产出**：Registry 可按 account_id 路由 Tiger 客户端；factory API 调用方无需修改

### M2 — 认证扩展与 UserContext

- `rbac_service.py` 扩展：`build_user_context()` 中查询 `user_broker_account_grants`
- `UserContext` 新增 `accessible_account_ids`、`default_account_id`、`account_grants`
- JWT payload 新增对应字段
- 新增 `app/core/account_context.py`：`get_current_account_id`、`require_account_access`

**产出**：登录响应和 `/api/v1/auth/me` 携带账户信息；依赖注入可按 account_id + grant_level 守卫

### M3 — 数据隔离层

- 逐步为主要服务层方法增加 `account_id` 参数（positions、signals、intents、attributions）
- 新增 `/api/v1/auth/my-accounts` 端点
- 当 `ACCOUNT_DATA_ISOLATION_V1131_ENABLED=True` 时，服务层自动注入 WHERE 过滤

**产出**：数据查询按授权账户过滤；feature flag 控制进退

### M4 — 账户管理 Admin API

- 新增 `app/routers/admin_broker_accounts.py`
- 实现 `GET/POST/PATCH/DELETE /api/v1/admin/broker-accounts`
- 实现 `GET/POST/PATCH/DELETE /api/v1/admin/users/{id}/account-grants`
- 所有操作写入 `authorization_audit_logs`

**产出**：管理员可通过 API 完整管理账户和用户授权

### M5 — 前端（Admin UI + WorkbenchShell 选择器）

- 新增 `AdminBrokerAccountsPage.vue`、`AdminUserAccountGrantsPage.vue`
- `auth` store 新增 `accessibleAccounts`、`currentAccountId`、`accountGrants`
- `WorkbenchShell.vue` 新增账户选择器（有多账户时展示）
- `client.ts` 拦截器注入 `X-Account-ID` 请求头
- 新增 `src/api/adminBrokerAccountService.ts`

**产出**：管理员 UI 完整可用；用户可切换操作账户；数据视图随账户切换刷新

---

## 8. 风险提示与安全要点

### 8.1 凭证存储安全

- `BROKER_CREDENTIAL_ENCRYPTION_KEY` 必须在生产部署时通过环境变量或 Secrets Manager 注入，不得提交到 Git。
- 私钥文件（.pem）不得以明文存储在 DB 中；上传 API 接收文件后立即加密存储，原始内容清除。
- API 响应中只返回 `key_fingerprint`（私钥公钥摘要），不返回加密后内容（防二次解密攻击）。

### 8.2 数据隔离边界

- 启用 `ACCOUNT_DATA_ISOLATION_V1131_ENABLED` 后，服务层每个 DB 查询需确保携带 `account_id` 过滤。  
- 数据隔离不影响 **策略库、回测配置、市场数据、RBAC 配置**等全局共享数据。
- 跨账户聚合查询（如管理员查看全局概览）必须明确声明为聚合读，且仅对 Administrator + ADMIN grant level 开放。

### 8.3 RiskGate 隔离

- 所有风控调用（RiskGate、CapacityArbiter、CircuitBreaker）必须在 `broker_account_id` 上下文中运行。
- 新增账户后，需为每个账户独立初始化 RiskGate 状态（不继承默认账户的风控状态）。

### 8.4 审计覆盖

- 账户注册、凭证更新、授权新增、授权变更、授权撤销均须写入 `authorization_audit_logs`（沿用 V11.2.1 审计机制）。

---

## 9. 验收标准

### Group A — 多账户接入

- [x] 系统可同时注册 2 个及以上 Tiger 账户
- [x] `BrokerAccountRegistry.get(account_id)` 返回对应账户的 Tiger 客户端实例
- [x] 当 `BROKER_ACCOUNT_REGISTRY_V1131_ENABLED=False` 时，factory 行为与 V11.2.1 相同
- [x] 新注册账户的 TigerOptionClient 可正常调用（至少能查询账户净值不报错）

### Group B — 账户数据隔离

- [x] 用户 A 只能查看授权账户的 positions、signals、intents；无授权账户返回 403
- [x] 使用 `account_id=X` 查询时，返回结果全部属于账户 X
- [x] `ACCOUNT_DATA_ISOLATION_V1131_ENABLED=False` 时，行为退回 V11.2.1（不过滤）
- [x] 数据隔离对 `/api/v1/positions`、`/api/v1/signals`、`/api/v1/order-book` 生效
- [x] 策略库（`/api/v1/strategies`）不隔离，所有授权用户可见

### Group C — 账户授权管理

- [x] 管理员可通过 `/api/v1/admin/broker-accounts` 完成账户 CRUD
- [x] 管理员可为用户配置和撤销账户授权（`/api/v1/admin/users/{id}/account-grants`）
- [x] `GET /api/v1/auth/my-accounts` 正确返回当前用户可访问的账户列表
- [x] 所有授权操作写入 `authorization_audit_logs`

### Group D — 前端体验

- [x] 管理员可通过 `AdminBrokerAccountsPage` 完成账户注册和凭证上传
- [x] 管理员可在用户详情页面为用户配置账户授权
- [x] 多账户用户登录后，WorkbenchShell 出现账户选择器
- [x] 切换账户后，当前页面数据刷新为对应账户数据

### Group E — 安全与治理

- [x] 凭证上传 API 不回显原始私钥和加密内容
- [x] 无账户访问权限的 API 请求返回 403，不泄露账户存在信息
- [x] RiskGate 调用携带 `broker_account_id`，风控计算按账户独立
- [x] 账户授权操作在审计日志中有完整记录（操作人、操作时间、变更内容）

---

## 10. 依赖与前置条件

| 前置 | 说明 |
| ---- | ---- |
| V11.2.1 RBAC | `RBAC_V1121_ENABLED=True`，用户、角色、权限体系完整 |
| Administrator 账户 | 至少存在一个 Administrator 角色用户，可完成账户和授权配置 |
| 凭证加密密钥 | `BROKER_CREDENTIAL_ENCRYPTION_KEY` 必须在迁移前设置 |
| DB 迁移完成 | 三张新表创建完毕，默认账户回补完成 |
| 单元测试基线 | M0 ORM 模型测试通过，M1 Registry 测试通过，再推进 M2-M5 |

---

## 11. 附录：与 LLM-Native Quant OS 提案的关系

[`docs/architecture/llm-native-quant-os.md`](../../../architecture/llm-native-quant-os.md) 描述了平台的长期认知架构演进方向。V11.3.1 的多账户基础设施为这一方向提供关键支撑：

- **多账户独立实验**：未来认知内核可在不同账户上并行运行策略实验（A/B），账户间数据隔离确保实验互不污染；
- **账户级 MetaState**：`MetaStateSnapshotService` 和 `ImprovementCandidateService` 可按账户维度独立运行，支持每个账户有独立的进化路径；
- **团队协作基础**：多账户 + 角色权限的组合，是平台从个人工具走向小型量化团队工具的基础设施层。

V11.3.1 是基础设施层，不改变认知架构。两者演进路径各自独立、互不干扰。
