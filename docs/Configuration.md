# 配置（环境变量）

本项目使用 `pydantic-settings` 从根目录 `.env` 读取配置。

- 模板：`.env.example`
- 配置加载逻辑：`backend/app/core/config.py`

## 必需配置

### 数据库

- `DATABASE_URL`（默认：`sqlite+aiosqlite:///./demo.db`）

> 当前版本默认 SQLite，适合本地开发；生产建议迁移到 Postgres（需要额外改造与部署支持）。

### 交易模式

- `TRADE_MODE`：`OFF` / `DRY_RUN` / `REAL`

说明：
- `OFF`：系统运行但不产生订单
- `DRY_RUN`：生成订单但不实际发送（推荐开发/测试）
- `REAL`：真实下单（请确保行情与权限齐备）

## 可选配置

### Tiger（券商/行情）

- `TIGER_ACCOUNT`：券商账户
- `TIGER_ID`：Tiger OpenAPI 开发者 ID
- `TIGER_PRIVATE_KEY_PATH`：RSA 私钥路径（.pem）
- `TIGER_QUOTE_MODE`：`DELAYED` / `REALTIME`
- `QUOTE_DATA_WARNING`：是否在 API 响应里提示延迟行情

未配置 `TIGER_ID` 或 `TIGER_PRIVATE_KEY_PATH` 时：系统会降级为 Dummy 客户端。

详见：[Integrations/Tiger](./Integrations/Tiger.md)

### OpenAI（AI 摘要/交易员风格解读）

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_MAX_TOKENS`
- `OPENAI_TIMEOUT_SECONDS`
- `OPENAI_API_BASE`（可选：镜像/网关，例如 `https://your-proxy-url.com/v1`）

详见：[Integrations/OpenAI](./Integrations/OpenAI.md)

### FRED（宏观数据）

- `FRED_API_KEY`

未配置时：宏观指标会使用降级/默认值策略（不会阻塞服务启动）。

### News API（地缘政治/新闻事件）

- `NEWS_API_KEY`

未配置时：地缘政治事件列表可能为空或使用默认值策略。

## 代理（OpenAI + FRED）

项目提供“配置级别”的代理开关：

- `PROXY_ENABLED`：`true/false`
- `HTTP_PROXY` / `HTTPS_PROXY`
- `NO_PROXY`

当 `PROXY_ENABLED=true` 时，服务启动会写入（同时写入大小写版本）：
- `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`

OpenAI SDK（httpx）与 FRED（requests/fredapi）会自动读取这些环境变量，从而通过代理访问。

> 当 `PROXY_ENABLED=false` 时，服务启动会主动清理进程内的 `HTTP(S)_PROXY/NO_PROXY`，避免外部 shell 环境变量造成“配置不确定”。

## 完整示例（建议从 .env.example 复制）

请直接参考 `.env.example`，它与当前代码实现保持一致。
