# Getting Started

## 1. 安装依赖

在仓库根目录：

- 进入后端目录：`backend/`
- 安装依赖：`pip install -r requirements.txt`

> 依赖安装细节与版本要求见：`backend/requirements.txt`

## 2. 准备配置

1) 复制模板：把 `.env.example` 复制成 `.env`

2) 按你的场景选择：

- **Dummy 模式（无需 Tiger）**：保持 `TIGER_ID` 与 `TIGER_PRIVATE_KEY_PATH` 为空即可。
- **Tiger 模式**：配置 `TIGER_ID`、`TIGER_PRIVATE_KEY_PATH`、`TIGER_ACCOUNT`。

3) 可选：配置 OpenAI（用于 AI 摘要/交易员风格解读）

- `OPENAI_API_KEY=...`
- 如需镜像/网关：`OPENAI_API_BASE=https://your-proxy-url.com/v1`

4) 可选：配置代理（用于 OpenAI + FRED 访问）

- `PROXY_ENABLED=true`
- `HTTP_PROXY/HTTPS_PROXY/NO_PROXY` 详见 [Configuration](./Configuration.md)

## 3. 启动服务

在 `backend/` 目录启动：

- `uvicorn app.main:app --reload --host 0.0.0.0 --port 8088`

> 端口不是强制的；文档示例默认使用 `8088`，以你的启动参数为准。

## 4. 最小验证（建议按顺序）

1) 健康检查（根级）：`GET /health`

2) 获取系统状态（根级）：`GET /ai/state`

3) 刷新持仓评估（/api/v1）：`POST /api/v1/positions/refresh`

4) 读取持仓评估（/api/v1）：`GET /api/v1/positions/assessment`

## 5. 常见问题

- **OpenAI 连接超时**：通常是网络/代理问题。优先启用 `PROXY_ENABLED`，或配置 `OPENAI_API_BASE`。
- **Tiger 未配置**：会自动降级为 Dummy 客户端（这对开发/接口联调是正常的）。
- **宏观数据为空**：未配置 `FRED_API_KEY` 时会进入降级/默认值策略。
