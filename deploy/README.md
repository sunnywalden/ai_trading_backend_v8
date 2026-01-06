# 部署指南（Docker + Kubernetes）

本文档用于将本项目后端（FastAPI）容器化并部署到 Kubernetes。

> 运行入口：`uvicorn app.main:app --host 0.0.0.0 --port 8088`

---

## 目录结构

- `deploy/Dockerfile`：镜像构建文件（build context 建议为仓库根目录）
- `deploy/k8s/*.yaml`：K8s manifests（Namespace / ConfigMap / Secret / Deployment / Service / PVC）

---

## 1) 构建与运行 Docker 镜像

### 1.1 本地构建

在仓库根目录执行：

- Dockerfile 路径：`deploy/Dockerfile`
- Build context：仓库根目录（用于 COPY backend/）

示例：
- 镜像名：`ai-trading-backend:local`
- 端口：容器 `8088`

> 说明：本仓库默认 SQLite。容器内建议把 DB 放到可挂载目录（例如 `/data/demo.db`），通过 `DATABASE_URL` 指定。

### 1.2 本地运行

### 1.2.1 使用 `.env`（推荐）

本项目使用 `pydantic-settings` 读取环境变量，并会在启动时从仓库中向上查找最近的 `.env` 文件（见 `backend/app/core/config.py`）。

建议做法：

1) 在仓库根目录从模板生成 `.env`（不要提交到 Git）：

```bash
cp .env.example .env
```

2) 编辑 `.env`，按需填写（常见项）：

- `DATABASE_URL`：本地可继续用默认 `sqlite+aiosqlite:///./demo.db`；容器内建议用绝对路径（如 `sqlite+aiosqlite:////data/demo.db`）
- `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_API_BASE`
- Tiger：`TIGER_ID`、`TIGER_PRIVATE_KEY_PATH`、`TIGER_ACCOUNT`
- 代理：`PROXY_ENABLED` + `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`

> 注意：镜像构建时不会把 `.env` 打包进镜像（仓库根目录的 `.dockerignore` 已忽略 `.env*`）。

### 1.2.2 Docker 运行时注入 `.env`

如果你用 Docker 在本机运行，推荐用 `--env-file` 传入 `.env`：

```bash
docker run --rm \
	-p 8088:8088 \
	--env-file ./.env \
	sunnywalden/ai-trading-backend:latest
```

如使用 SQLite 且希望数据持久化，建议同时挂载 `/data` 并设置：

- `.env` 中：`DATABASE_URL=sqlite+aiosqlite:////data/demo.db`
- 运行时：`-v $(pwd)/data:/data`

关键环境变量（最小集合）：

- `DATABASE_URL`：建议 `sqlite+aiosqlite:////data/demo.db`
- `TRADE_MODE`：`DRY_RUN` / `REAL` / `OFF`

可选能力：

- Tiger：`TIGER_ID`、`TIGER_PRIVATE_KEY_PATH`、`TIGER_ACCOUNT`、`TIGER_QUOTE_MODE`
- OpenAI：`OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_API_BASE`
- 代理：`PROXY_ENABLED` + `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`

健康检查：
- `GET /health`

---

## 2) Kubernetes 部署（kubectl）

> K8s 中通常不直接使用 `.env` 文件；推荐把非敏感配置放入 ConfigMap，把密钥放入 Secret。

### 2.1 准备镜像

1) 把 `deploy/k8s/deployment.yaml` 中的镜像地址替换：

- `image: REPLACE_ME/ai-trading-backend:latest`

2) 推送镜像到你的镜像仓库（Docker Hub / ECR / GCR / ACR 等）。

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

- `kubectl -n ai-trading create secret generic tiger-keys --from-file=tiger_private_key.pem=./backend/keys/your.pem`

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

