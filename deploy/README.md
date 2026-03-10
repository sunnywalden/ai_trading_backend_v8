# 部署指南（Docker + Kubernetes）

本文档用于将本项目后端（FastAPI）容器化并部署到 Kubernetes。

> 运行入口：`uvicorn app.main:app --host 0.0.0.0 --port 8088 --reload`

---

## 目录结构

- `deploy/Dockerfile`：镜像构建文件（build context 建议为仓库根目录）
- `deploy/k8s/*.yaml`：K8s manifests（Namespace / ConfigMap / Secret / Deployment / Service / PVC）

---

## 1) 构建与运行 Docker 镜像

### 1.1 本地构建

在仓库根目录执行：

- Dockerfile 路径：`deploy/Dockerfile`
- Build context：仓库根目录（构建时会把仓库复制到容器内部 `/app/`）

示例构建命令：

```bash
# 在 ai_trading_backend_v8 目录下执行
docker build -f deploy/Dockerfile --platform linux/arm64 -t sunnywalden/ai-trading-backend:latest .
docker tag sunnywalden/ai-trading-backend:latest sunnywalden/ai-trading-backend:v1.0.0
docker push sunnywalden/ai-trading-backend:latest
docker push sunnywalden/ai-trading-backend:v1.0.0
```

- 镜像名：`sunnywalden/ai-trading-backend:latest`
- 端口：后端容器内部 `8088`

> 前端镜像构建请前往 `ai_trading_frontend_v4/deploy/` 目录参考相关文档。

> 说明：本仓库默认 SQLite。容器内建议把 DB 放到可挂载目录（例如 `/data/demo.db`），通过 `DATABASE_URL` 指定。

### 1.2 本地运行

### 1.2.1 使用 `.env`（推荐、且已同步到 `.env.example`）

本项目使用 `pydantic-settings` 读取环境变量（见 `app/core/config.py`）；仓库根目录包含一个最新的 `.env.example`，建议复制并填充后再运行：

```bash
cp .env.example .env
# 必填（至少）: DATABASE_URL / JWT_SECRET_KEY
# 可选（取决于功能）: OPENAI_API_KEY / TIGER_ID / TIGER_PRIVATE_KEY_PATH / PROXY_ENABLED
```

安全建议：
- 不要将 `.env` 提交到 Git；使用 Vault/Secrets Manager 或 CI Secret 注入生产密钥。
- `.env.example` 仅为示例，已替换所有敏感值为占位符。

> 开发快速启动（SQLite 默认）:
> `DATABASE_URL=sqlite+aiosqlite:///./demo.db`（无需额外依赖）

### 1.2.2 Docker 运行时注入 `.env`

运行示例（开发/本地）：

```bash
# 在仓库根目录
docker run --rm \
  -p 8088:8088 \
  --env-file ./.env \
  -v $(pwd)/data:/data \  # 可选：用于持久化 sqlite
  sunnywalden/ai-trading-backend:latest
```

关键环境变量（最小集合）示例：

- `DATABASE_URL`（容器内示例）：`sqlite+aiosqlite:////data/demo.db` 或 `mysql+aiomysql://user:pwd@host:3306/db`
- `TRADE_MODE`：`DRY_RUN`（开发）/ `REAL`（生产）
- `JWT_SECRET_KEY`：生产环境务必设置强随机值

环境注入建议：
- 本地：使用 `--env-file .env`
- CI/CD：通过仓库/构建平台的 Secret 注入环境变量
- Kubernetes：使用 ConfigMap（非敏感）与 Secret（敏感）注入

> 注意：`deploy/docker-compose.yml` 中已把 `.env` 与 `volumes` 作为示例（请替换成你自己的 Secret/Volumes）。
---

## 2) 线上环境部署与 SSL 支持 (Traefik)

在生产环境，我们使用 **Traefik** 作为反向代理，并集成 Let's Encrypt 自动获取 SSL 证书。

### 2.1 准备域名与配置

1. 确保你的服务器公网 IP 已绑定域名（例如 `ai-trading.example.com` 和 `api.ai-trading.example.com`）。
2. 在项目根目录的 `.env` 中配置以下变量：
   - `ACME_EMAIL`: 你的邮箱（用于接收证书到期通知）。
   - `FRONTEND_DOMAIN`: 前端访问域名。
   - `BACKEND_DOMAIN`: 后端 API 访问域名。

### 2.2 启动服务

在 `deploy/` 目录下执行：

```bash
docker compose up -d
```

### 2.3 Traefik 工作原理
- **入口**: 监听 80 (HTTP) 和 443 (HTTPS) 端口。
- **自动跳转**: 所有 HTTP 请求会自动重定向到 HTTPS。
- **证书存储**: 证书信息存储在 `deploy/letsencrypt/acme.json` 中，请确保该文件权限正确（`600`）。
- **服务发现**: Traefik 通过容器标签 (Labels) 自动识别 `backend` 和 `frontend` 服务并进行路由转发。

---

## 3) Redis 与 MySQL（前置依赖）

本项目在生产或完整部署时通常依赖 Redis（缓存、监控计数）和 MySQL（持久化）。可选使用 SQLite 作为轻量替代。

- Redis envs（示例）:
  - `REDIS_ENABLED=true`
  - `REDIS_HOST=redis.example.local`
  - `REDIS_PORT=6379`
  - `REDIS_DB=0`
  - `REDIS_PASSWORD=`（如果有）
  - 也可使用 `REDIS_URL=redis://:password@host:6379/0`

- MySQL（示例）：
  - `DATABASE_URL=mysql+aiomysql://user:password@mysql:3306/ai_trading`

> Docker Compose：项目包含 `deploy/docker-compose.yml`，适合在同一主机上快速运行 `db + redis + backend` 用于本地集成测试。

---

### 初始化数据库与迁移

仓库提供简单的初始化脚本：

- `python init_db.py`：创建并初始化必要表（调用 `engine.dispose()` 后优雅退出）
- `python create_position_macro_tables.py`：创建特定的 schema 表（如有需要）

在容器中执行这些脚本时请确保 `DATABASE_URL` 环境变量已正确注入（或在 Kubernetes 使用 Job 运行初始化）。

### V10.5.3 上线 SOP（迁移 → 回填 → 灰度开关 → 验收）

V10.5.3 引入了 `execution_policy_profiles`（执行策略长期反馈画像），并新增四个收益质量升级开关：

- `ALPHA_TRUTH_V2_ENABLED`
- `SEAT_VALUE_ARBITER_ENABLED`
- `EXECUTION_POLICY_HARD_CONTROL_ENABLED`
- `GOVERNANCE_HARD_GATE_ENABLED`

> 建议：**不要第一次发布就四个一起全开**。推荐先完成迁移和回填，再按 Observe → Seat Value → Execution Hard Control → Governance Hard Gate 的顺序逐步开启。

#### 0) 发布前准备

1. 备份 MySQL（至少备份 `execution_quality_log`、`autonomous_execution_intent`、`execution_policy_profiles`）。
2. 确认镜像版本已推送，例如：`sunnywalden/ai-trading-backend:v10.5.3`。
3. 确认目标环境的 `.env` / ConfigMap / Secret 已包含 V10.5.3 所需开关。
4. 建议第一次上线先保持：

```dotenv
ALPHA_TRUTH_V2_ENABLED=true
SEAT_VALUE_ARBITER_ENABLED=false
EXECUTION_POLICY_HARD_CONTROL_ENABLED=false
GOVERNANCE_HARD_GATE_ENABLED=false
```

#### 1) 执行数据库迁移

先检查：

```bash
python scripts/migrations/upgrade_to_v10_5_3.py --check
```

> Windows 提示：如果 `python` 指向 `C:\Users\<you>\AppData\Local\Microsoft\WindowsApps\python.exe`，优先使用项目虚拟环境解释器：` .venv\Scripts\python.exe scripts/migrations/upgrade_to_v10_5_3.py --check `。V10.5.3 相关脚本已尝试自动切换到 `.venv`，但显式使用 `.venv` 仍然最稳妥。

若目标表不存在，再执行：

```bash
python scripts/migrations/upgrade_to_v10_5_3.py
```

迁移内容：

- 新建 `execution_policy_profiles`
- 为 Execution Closed Loop 提供长期反馈画像存储

#### 2) 执行历史回填（默认 dry-run）

先 dry-run 观察历史数据规模：

```bash
python scripts/migrations/backfill_execution_policy_profiles.py
```

如果结果符合预期，再真正写入：

```bash
python scripts/migrations/backfill_execution_policy_profiles.py --execute
```

如果希望先对单账户灰度：

```bash
python scripts/migrations/backfill_execution_policy_profiles.py --execute --account-id 2127xxxx
```

#### 3) 执行一致性修复 / 校验（默认 dry-run）

先检查是否存在以下异常：

- missing profiles
- orphan profiles
- stale profiles
- duplicate keys

```bash
python scripts/maintenance/repair_execution_policy_profiles.py
```

若检查结果非空，再执行修复：

```bash
python scripts/maintenance/repair_execution_policy_profiles.py --execute
```

单账户灰度：

```bash
python scripts/maintenance/repair_execution_policy_profiles.py --execute --account-id 2127xxxx
```

#### 4) 发布后第一阶段：Observe 模式

建议先只开启：

```dotenv
ALPHA_TRUTH_V2_ENABLED=true
SEAT_VALUE_ARBITER_ENABLED=false
EXECUTION_POLICY_HARD_CONTROL_ENABLED=false
GOVERNANCE_HARD_GATE_ENABLED=false
```

目标：

- 让 `/api/v1/alpha-lab/snapshot` 输出真相四层收益口径
- 不改变席位竞争排序、不改变真实执行算法、不收紧毕业门槛

重点观察：

- `/api/v1/alpha-lab/snapshot?lookback_days=30`
- `summary.gross_return / net_return / after_cost_return / after_turnover_return`
- `shadow_book`

#### 5) 第二阶段：启用 Seat Value 排序

当 Alpha Truth 观察稳定后，可开启：

```dotenv
SEAT_VALUE_ARBITER_ENABLED=true
```

目标：

- 让席位竞争从 `admission_score` 排序升级为 `seat_value` 排序
- 在 `/api/v1/capacity/preview` 中观察 explainability 字段

重点观察：

- `/api/v1/capacity/config`
- `/api/v1/capacity/preview`
- `/api/v1/capacity/stats`

关键字段：

- `seat_value`
- `marginal_alpha`
- `marginal_risk`
- `marginal_turnover`
- `replace_or_hold_reason`

#### 6) 第三阶段：启用 Execution Hard Control

当持仓替换逻辑稳定后，再开启：

```dotenv
EXECUTION_POLICY_HARD_CONTROL_ENABLED=true
```

目标：

- 从 Observe Only 升级为 Hard Control
- 执行层开始真正使用策略画像反馈调整算法与参与率

重点观察：

- `/api/v1/execution-policy/overview`
- `/api/v1/execution-policy/intents/{intent_id}`

关键字段：

- `control_state.mode`
- `persistent_profile`
- `feedback_profile`
- `policy.slippage_budget_bps`

#### 7) 第四阶段：启用 Governance Hard Gate

最后再开启：

```dotenv
GOVERNANCE_HARD_GATE_ENABLED=true
```

目标：

- 将 Governance Pipeline 从展示/观察升级为真正 Promotion Gate
- 无完整 evidence chain 的策略不能进入更高阶段

重点观察：

- `/api/v1/governance/pipeline?limit=10`
- Paper 毕业检查结果中的 `governance_gate`

关键字段：

- `evidence_chain`
- `promotion_blockers`
- `stage`
- `rollback_suggestion`

#### 8) 发布后 Smoke Check

建议至少校验以下接口：

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/v1/alpha-lab/snapshot?lookback_days=30
curl http://127.0.0.1:8088/api/v1/capacity/config
curl http://127.0.0.1:8088/api/v1/capacity/preview
curl http://127.0.0.1:8088/api/v1/execution-policy/overview?limit=5
curl http://127.0.0.1:8088/api/v1/governance/pipeline?limit=10
```

若前后端一并发布，再补：

- `/alpha-lab`
- `/portfolio`
- `/execution-policy`
- `/governance/pipeline`

#### 9) 回滚策略

若上线后发现问题，建议按下面顺序回退：

1. **先关开关**（最快、最安全）

```dotenv
SEAT_VALUE_ARBITER_ENABLED=false
EXECUTION_POLICY_HARD_CONTROL_ENABLED=false
GOVERNANCE_HARD_GATE_ENABLED=false
```

必要时只保留：

```dotenv
ALPHA_TRUTH_V2_ENABLED=true
```

2. 若仅画像数据异常：

- 重新执行 `backfill_execution_policy_profiles.py --execute`
- 再执行 `repair_execution_policy_profiles.py --execute`

3. 若必须回滚 schema：

```bash
python scripts/migrations/upgrade_to_v10_5_3.py --rollback
```

> 注意：schema rollback 会删除 `execution_policy_profiles`，请先确认数据已备份。

#### 10) 推荐上线节奏

- **T0**：迁移 + 回填 + repair dry-run/execute
- **T0 ~ T+1d**：仅开 `ALPHA_TRUTH_V2_ENABLED`
- **T+1d ~ T+3d**：开启 `SEAT_VALUE_ARBITER_ENABLED`
- **T+3d ~ T+5d**：开启 `EXECUTION_POLICY_HARD_CONTROL_ENABLED`
- **T+5d 以后**：开启 `GOVERNANCE_HARD_GATE_ENABLED`

如果是测试/灰度环境，且你已经完成专项回归与联调，也可以直接四个全开；但生产环境仍建议按阶段推进，别让四个新齿轮第一次见面就一起高速运转。

---

### API 监控（Monitoring）与健康检查

系统内置 API 调用频率监控（FRED/NewsAPI/Tiger/Yahoo/OpenAI），并提供一组 REST 端点：

- `GET /api/v1/monitoring/health` — 汇总健康/告警状态
- `GET /api/v1/monitoring/stats` — 获取各 API 的调用统计（支持 `time_range=day|hour|minute`）
- `GET /api/v1/monitoring/report` — 生成一次性监控报告（包括错误样本与策略）
- `GET /api/v1/monitoring/rate-limit/{provider}` — 检查某个 API 的限额状态
- `GET /api/v1/monitoring/policies` — 查看内置的 Rate Limit 策略

这些端点默认随服务启用并依赖 Redis 存储采样与计数。

---

### 前端开发注意（代理 / CORS）

- 前端开发服务器（例如 Vite）在开发时通常运行在 `http://localhost:5173`，请配置代理把 `/api` 转发到后端（示例 Vite 配置）：

```js
// vite.config.js (示例)
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8088',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
```

- 后端已配置 CORS（开发环境允许所有来源），生产部署请务必限制 `allow_origins`。

---

### Smoke tests 与 CI（验证部署健康）

项目包含端到端 Smoke Test 脚本：`smoke_test.py`（位于 `tests/integration/`）。建议在部署后或 CI 管道中运行：

```bash
python tests/integration/smoke_test.py
```

它会验证：健康端点、关键 API、Redis 缓存、数据库写读、调度器基本信息以及 API 监控端点（共 13 项测试）。

---

### 运行与监控（示例）

开发（可热重载）:

```bash
# 在仓库根目录下
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

生产（建议）：

- 运行 Uvicorn/ Gunicorn + Uvicorn workers
- 端口：容器对外暴露 `8088`

> 重要：确保在应用关闭阶段显式释放异步 DB engine（`await engine.dispose()`）与 Redis client（`await redis_client.close()`），以避免在事件循环关闭后出现 aiomysql 的 `Connection.__del__` 警告。

---

健康检查：
- `GET /health`（服务基础健康）
- `GET /api/v1/monitoring/health`（监控子系统健康）

---

以上补充将有助于生产部署和本地调试。如需我把这些更改提交到仓库（并推送一个 commit），我可以现在提交并推送。

---

## 2) Kubernetes 部署（kubectl）

> K8s 中通常不直接使用 `.env` 文件；推荐把非敏感配置放入 ConfigMap，把密钥放入 Secret。

### 2.1 准备镜像

1) 把 `deploy/k8s/deployment.yaml` 中的镜像地址替换：

- `image: REPLACE_ME/ai-trading-backend:latest`

2) 推送镜像到你的镜像仓库（Docker Hub / ECR / GCR / ACR 等）。

示例推送命令：

```bash
# 使用 Docker Hub 或通用 Registry（替换 yourrepo）
docker tag ai-trading-backend:local yourrepo/ai-trading-backend:latest
docker push yourrepo/ai-trading-backend:latest

# 直接构建并推送
docker build -f deploy/Dockerfile -t yourrepo/ai-trading-backend:latest .
docker push yourrepo/ai-trading-backend:latest

# AWS ECR 示例（替换 region/account）
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
docker tag ai-trading-backend:local <account>.dkr.ecr.<region>.amazonaws.com/ai-trading-backend:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/ai-trading-backend:latest
```

### 2.2 创建 Namespace、配置与存储

按顺序 apply：

1) `deploy/k8s/namespace.yaml`
2) `deploy/k8s/pvc.yaml`
3) `deploy/k8s/configmap.yaml`
4) `deploy/k8s/secret.yaml`

> 注意：`deploy/k8s/secret.yaml` 里包含占位的 `OPENAI_API_KEY`，请替换。

如果你已经有一份本地 `.env`，可以把内容拆分成：

- 非敏感项（例如 `DATABASE_URL`、`OPENAI_MODEL`、`ENABLE_SCHEDULER`）→ 写入 `deploy/k8s/configmap.yaml`
- 敏感项（例如 `OPENAI_API_KEY`、`FRED_API_KEY`、`NEWS_API_KEY`、`TIGER_ID`）→ 写入 `deploy/k8s/secret.yaml`

然后由 `deployment.yaml` 使用 `envFrom` 注入到容器中。

### 2.3 Tiger 私钥（可选）

如果你要用 Tiger（真实账户持仓/行情），推荐把私钥文件做成 K8s Secret 并挂载到容器 `/keys`：

- Secret 名称：`tiger-keys`
- key 文件名：`tiger_private_key.pem`

创建方式示例（供参考）：

- `kubectl -n ai-trading create secret generic tiger-keys --from-file=tiger_private_key.pem=./keys/your.pem`

然后确保：

- `TIGER_PRIVATE_KEY_PATH=/keys/tiger_private_key.pem`

### 2.4 应用 Deployment/Service

- `deploy/k8s/deployment.yaml`
- `deploy/k8s/service.yaml`

启动后检查：

- Pod 就绪探针：`/health`
- Service 连通性：Cluster 内 `http://ai-trading-backend.ai-trading.svc.cluster.local/health`

---

## 3) 关于 Scheduler（非常重要）

本项目启动时会注册并运行定时任务（刷新技术面/宏观等）。

- K8s 多副本时，如果每个 Pod 都运行 scheduler，会导致任务重复执行。
- 本次已支持通过环境变量控制：`ENABLE_SCHEDULER`。

建议：

- 方式A（最简单）：保持 `replicas: 1`
- 方式B（更标准）：Deployment 多副本 + `ENABLE_SCHEDULER=false`，另起单独的 worker（未来可做 CronJob/单独 Deployment）

---

## 4) 常见问题排查

### 4.1 /health 不通
- 检查容器端口：容器内 `8088`，Service 把 `80 -> 8088`
- 检查 readinessProbe/livenessProbe path 是否为 `/health`

### 4.2 SQLite 文件丢失/重建
- 确认 `DATABASE_URL` 使用了绝对路径（建议 `/data/demo.db`）
- 确认 Deployment 挂载了 PVC 到 `/data`

### 4.3 Tiger 无法读取私钥
- 确认 secret 挂载到了 `/keys`
- 确认 `TIGER_PRIVATE_KEY_PATH=/keys/tiger_private_key.pem`

### 4.4 OpenAI/FRED 访问失败
- 在集群需要代理时：设置 `PROXY_ENABLED=true` 并填入 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`

