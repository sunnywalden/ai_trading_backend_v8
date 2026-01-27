# 认证说明

本系统新增基于 JWT 的简易认证机制（默认开启）。

主要要点：

- 默认情况下 **AUTH_ENABLED=true**（在 `app/core/config.py` 中默认启用）。未认证的用户无法使用系统的 API（除 `/health` 与 `/api/v1/login`）。
- 管理员账号通过环境变量配置： `ADMIN_USERNAME`、`ADMIN_PASSWORD`（请在生产环境通过 `.env` 覆盖默认值），用于登录换取 Bearer token（JWT）。
- JWT 签发使用 `JWT_SECRET_KEY`，请设置为随机且安全的值； `ACCESS_TOKEN_EXPIRE_MINUTES` 指定 token 过期分钟数（默认 60 分钟）。

登录接口（换取 token）：

- POST /api/v1/login
  - Content-Type: application/x-www-form-urlencoded
  - 参数： `username`、`password`（和 OAuth2 密码模式一致）
  - 返回： `{ "access_token": "<token>", "token_type": "bearer" }`

使用方式：

- 在后续请求中在 HTTP Header 中添加：
  - `Authorization: Bearer <token>`

注意事项：

- 目前实现为单管理员认证（用户名/密码在配置中定义）。后续可扩展为用户表、RBAC 或第三方身份提供者。
- 强烈建议在 `.env` 中覆盖 `ADMIN_PASSWORD` 与 `JWT_SECRET_KEY`，并使用 HTTPS 保护传输。