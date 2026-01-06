# OpenAI 集成（AI 摘要/回退/代理/镜像）

## 配置项

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_MAX_TOKENS`
- `OPENAI_TIMEOUT_SECONDS`
- `OPENAI_API_BASE`（可选：镜像/网关，例如 `https://your-proxy-url.com/v1`）

## 行为与回退策略（实现导向）

- 未配置 `OPENAI_API_KEY`：不会阻塞服务启动；相关 AI 摘要会走规则引擎/默认摘要。
- 配置了 key 但网络失败/超时：会按回退链尝试（实现内有可用模型缓存 + 回退偏好），最终仍可降级为规则摘要。

## 代理支持

推荐通过 `.env` 管理代理（同时影响 OpenAI 与 FRED）：

- `PROXY_ENABLED=true`
- `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`

OpenAI SDK 底层 httpx 默认会读取这些环境变量。

## 输出约束

项目在部分场景会对 AI 输出加硬约束（例如“日线走势结论不输出趋势信心/可信度数值”）。
如需调整输出模板，请查看并修改 `backend/app/services/ai_analysis_service.py` 中对应 prompt 构造方法。
