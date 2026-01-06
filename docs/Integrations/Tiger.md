# Tiger 集成（券商/行情）

## 配置项

- `TIGER_ACCOUNT`
- `TIGER_ID`
- `TIGER_PRIVATE_KEY_PATH`
- `TIGER_QUOTE_MODE`：`DELAYED` / `REALTIME`

> 以 `backend/app/core/config.py` 为准。

## 行情模式与风控约束

- `DELAYED`（免费延迟行情，约 15–20 分钟）：适合开发联调，不建议用于实盘自动对冲。
- `REALTIME`（实时行情，需订阅）：生产环境推荐，尤其是涉及自动对冲/风险限额判断的场景。

## 降级策略

未配置 `TIGER_ID` 或 `TIGER_PRIVATE_KEY_PATH` 时：
- 券商相关能力会使用 Dummy 客户端
- 部分 Greeks/持仓相关数据可能为 0 或空（这不影响接口结构，但会影响业务判断）

## 常见问题

- 私钥路径：支持相对路径与绝对路径（相对路径会基于项目根目录解析）。
- 行情延迟提示：可通过 `QUOTE_DATA_WARNING` 控制是否在 API 返回中提示延迟风险。
