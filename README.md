# AI Trading Backend V8

## 🎯 项目简介

AI Trading Backend V8 是一个基于 FastAPI 的**交易风控 + 持仓评估 + 宏观风险 + 机会扫描**后端。

核心能力：

- **风险管理与自动对冲**：Greeks 暴露、风险限额、自动对冲（可 DRY_RUN）
- **行为画像**：基于历史成交/盈亏抽取交易行为特征（卖飞、过度交易、报复性交易等）
- **持仓评估**：技术面/基本面/情绪合成评分，并提供日线走势快照（持久化缓存）
- **宏观风险 & Opportunities**：宏观风险概览 + 每日机会扫描
- **AI 能力（可选）**：OpenAI 用于生成摘要/解读；未配置会降级为规则摘要

> 文档入口（权威）：`docs/README.md`

## 📚 文档（请从这里开始）

- [docs/PRODUCT.md](docs/PRODUCT.md) — 产品需求（Alpha Loop / 核心功能）
- [docs/API.md](docs/API.md) — API 参考
- [docs/BACKEND_DESIGN.md](docs/BACKEND_DESIGN.md) — 后端架构设计

> 其余历史或实现细节已归档到 `docs/archived/`，如需查看请到该目录检索历史记录。

## 🚀 核心功能

### 1. 实时风险监控

系统持续监控以下风险指标：

- **Greeks 敞口**：
  - Delta：方向性风险（占净值百分比）
  - Gamma：Delta 变化率（二阶风险）
  - Vega：波动率风险
  - Theta：时间衰减
  - 短期 DTE Greeks（近期到期期权的额外风险）

- **风险限额**：
  - 单笔订单名义金额上限
  - 总 Gamma/Vega/Theta 占净值百分比上限
  - 按标的分层管理（T1/T2/T3 风险等级）

### 2. 交易行为分析

基于历史成交数据，系统自动分析以下交易行为模式：

- **卖飞行为**：低位卖出后在更高价买回的损失
- **过度交易**：频繁进出、持仓周期过短
- **报复性交易**：大额亏损后短时间内放大仓位
- **追高行为**：高价追入后快速回撤

每个标的生成 0-100 分的行为评分，用于动态调整风控参数。

### 3. 自动对冲引擎

当风险敞口超标时，系统自动：

1. 计算当前风险状态
2. 生成多种对冲方案（现货/期权对冲）
3. 评估每种方案的成本效益
4. 自动执行最优对冲订单（可配置为 DRY_RUN 模式）

### 4. AI 决策助手

集成 OpenAI 模型（以 `OPENAI_MODEL` 配置为准），提供智能交易建议：

- **输入**：交易目标、风险偏好、时间维度
- **分析**：自动聚合账户状态、Greeks 敞口、行为画像
- **输出**：结构化的交易建议、具体订单草案、风险提示

## ✅ 运行（最短路径）

1) 从 `.env.example` 生成 `.env` 并按需填写（不要提交含密钥的 `.env` 到 Git）

```bash
cp .env.example .env
# 编辑 .env，至少设置：DATABASE_URL / OPENAI_API_KEY / JWT_SECRET_KEY
```

2) 安装依赖并激活虚拟环境（在仓库根目录执行）：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3) 启动开发服务器：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

4) 快速验证：
- `GET /health`（公开）
- `POST /api/v1/login`（表单提交 username/password，获取 Bearer token）
- 使用 `Authorization: Bearer <token>` 访问受保护接口，如：
  - `GET /api/v1/ai/state`
  - `POST /api/v1/positions/refresh`
  - `GET /api/v1/positions/assessment`

> Tip: `.env.example` 与仓库内 `docs/` 已同步；示例文件中不会包含真实密钥或密码。请在部署前使用安全的密钥管理工具（Vault / Secrets Manager / Kubernetes Secret）。

## ⚙️ 配置

配置请以 [docs/Configuration.md](docs/Configuration.md) 为准（统一口径，避免多份文档冲突）。

### Tiger Open API 配置步骤

1. **登录老虎开放平台**：访问 [https://quant.itigerup.com](https://quant.itigerup.com)
2. **获取开发者 ID (tiger_id)**：在"我的应用"中查看
3. **生成 RSA 密钥对**：
   ```bash
   # 生成私钥
   openssl genrsa -out private_key.pem 1024
   # 生成公钥
   openssl rsa -in private_key.pem -pubout -out public_key.pem
   ```
4. **上传公钥**：在开放平台"密钥管理"中上传 public_key.pem
5. **配置环境变量**：将私钥路径和 tiger_id 填入 .env 文件

详细文档：https://quant.itigerup.com/openapi/zh/python/quickStart/prepare.html

### 行情数据说明

老虎证券提供两种行情模式：

- **延迟行情（免费）**：
  - ✅ 免费使用
  - ✅ 适合开发测试
  - ⚠️ 数据延迟 15-20 分钟
  - ❌ 不适合实盘自动对冲

- **实时行情（付费）**：
  - ✅ 秒级延迟
  - ✅ 生产环境必备
  - ✅ 准确风险评估
  - 💰 需要订阅（约 $10-50/月）

**购买方式**：登录[开发者中心](https://developer.itigerup.com/profile)或 Tiger Trade APP

行情延迟/实时与风险提示：
- 权威说明：[`docs/Integrations/Tiger.md`](docs/Integrations/Tiger.md)
- 历史评估占位（全文请走 Git 历史）：[`docs/legacy/QUOTE_DATA_ANALYSIS.md`](docs/legacy/QUOTE_DATA_ANALYSIS.md)

### 交易模式说明

- **OFF**：系统运行但不生成任何订单
- **DRY_RUN**：生成订单但仅打印，不实际发送（推荐测试）
- **REAL**：真实下单到券商（⚠️ 谨慎使用，需实时行情）

## 🛠️ 安装与运行

### 环境要求

- Python 3.10+
- SQLite（用于本地数据存储）
- Tiger 证券账户（可选，用于连接真实 API）

### 安装依赖

```bash
pip install -r requirements.txt
```

说明：已启用 `orjson` 作为 FastAPI 的高性能 JSON 序列化依赖（提升接口响应速度）。

### 配置 Tiger API（可选）

如需连接真实 Tiger API，请参考 [`docs/Integrations/Tiger.md`](docs/Integrations/Tiger.md) 完成配置。

不配置 Tiger API 时系统将使用 Dummy 客户端（测试模式）。

### 测试 API 连接

```bash
# 运行测试脚本验证配置
python tests/integration/test_tiger_api.py
```

### 初始化数据库

```bash
# 系统首次运行时会自动创建 demo.db 数据库
python -m app.main
```

### 启动服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问 API 文档：[http://localhost:8000/docs](http://localhost:8000/docs)

### 运行行为评分任务

```bash
python -m app.jobs.behavior_rebuild_job
```

## 📊 数据库表结构

### symbol_behavior_stats

存储各标的的交易行为统计和评分：

- `account_id`：账户 ID
- `symbol`：标的代码
- `window_days`：统计时间窗口
- `trade_count`：总交易笔数
- `sell_fly_events`：卖飞事件次数
- `overtrade_index`：过度交易指数
- `revenge_events`：报复性交易次数
- `behavior_score`：综合行为评分（0-100）
- `sell_fly_score` / `overtrade_score` / `revenge_trade_score`：各维度评分

### symbol_risk_profile

存储各标的的风险配置：

- `account_id`：账户 ID
- `symbol`：标的代码
- `tier`：风险等级（T1/T2/T3）
- `max_single_order_usd`：单笔订单上限
- `max_total_exposure_usd`：总敞口上限

### position_trend_snapshots

存储每日日线趋势快照，供持仓评估组件（以华尔街交易员视角）快速呈现短/中期走势：

- `account_id`：账户 ID（示例为 demo-account）
- `symbol`：标的代码
- `timeframe`：时间框架（目前固定 `1D`）
- `trend_direction`、`trend_strength`：趋势方向与强度（短/中期）
- `trend_description`：一句话趋势描述（用于 AI 摘要）
- `rsi_value`、`rsi_status`、`macd_status`：指标状态
- `bollinger_position`、`volume_ratio`：布林带位置与成交量活跃度
- `support_levels` / `resistance_levels`：支撑/阻力列表（JSON serialized）
- `ai_summary`：华尔街风格的技术面解读
- `timestamp`：快照时间（每天只保留最新一条）

该表由技术分析服务每日刷新（`TechnicalAnalysisService` 读取 1D 数据、计算 MA/RSI/MACD/布林/支撑阻力/量价比并写入），
并供 `/positions/assessment` 直接拉取趋势快照，确保短/中期走势可以以 Wall Street 语言在前端展示。

注意：宏观风险分析模块保持独立，引用的是更长周期的 FRED/CPI/利率等数据，**不会与上述日线趋势快照耦合**。

## �️ 数据库迁移

### 版本管理

本项目使用版本化的数据库迁移脚本，确保数据库结构随代码同步更新。

### 快速开始

```bash
# 1. 初始化版本管理
python scripts/migrations/version_manager.py --init

# 2. 查看当前版本
python scripts/migrations/version_manager.py --current

# 3. 升级数据库（例如升级到 v3.1.1）
python scripts/migrations/upgrade_to_v3.1.1.py

# 4. 验证数据库结构
python scripts/migrations/verify_v3.1.1.py

# 5. 记录版本
python scripts/migrations/version_manager.py --record v3.1.1
```

### 生产环境升级

⚠️ 生产环境升级前务必：
1. 完整备份数据库
2. 在测试环境验证升级流程
3. 选择低峰期执行
4. 准备回滚方案

```bash
# 备份数据库
mysqldump -u root -p ai_trading > backup_$(date +%Y%m%d_%H%M%S).sql

# 执行升级（需要确认）
python scripts/migrations/upgrade_to_v3.1.1.py --production

# 验证结果
python scripts/migrations/verify_v3.1.1.py
```

### 版本历史

| 版本 | 主要变更 |
|------|---------|
| v3.1.2 | 修复联调接口错误，优化前端导航交互，完善数据库迁移工具链 |
| v3.1.1 | 新增策略通知表、信号性能跟踪表；扩展至15个策略；添加 action/direction/strategy_id 字段 |
| v2.2.2 | 基础版本 |

### 详细文档

- [数据库迁移完整指南](docs/DATABASE_MIGRATIONS.md) - 详细的表结构和升级说明
- [迁移脚本文档](scripts/migrations/README.md) - 脚本使用和开发指南

## �🔧 技术栈

- **Web 框架**：FastAPI
- **异步 ORM**：SQLAlchemy (async)
- **数据库**：SQLite (aiosqlite)
- **数据验证**：Pydantic
- **AI 模型**：OpenAI（由 `OPENAI_MODEL` 配置）
- **券商接口**：Tiger Open API

## 🎯 使用场景

1. **期权做市商**：实时监控多标的 Greeks 敞口，自动执行对冲策略
2. **量化基金**：集成 AI 决策辅助，提升风险管理效率
3. **个人交易者**：分析自身交易行为，识别不良交易模式
4. **风险管理团队**：多层级风控体系，支持模拟和实盘模式切换

## ⚠️ 风险提示

1. 本系统为演示和研发用途，请勿直接用于实盘交易
2. 使用 REAL 模式前务必充分测试并设置合理的风险限额
3. AI 建议仅供参考，最终决策需人工审核
4. 期权交易具有高风险，请确保充分了解相关知识

## 📝 开发日志

- **V8 版本**：完整的风险管理、行为分析和 AI 决策系统
- 支持 Tiger 券商和 Dummy 模拟客户端
- 实现多维度行为评分引擎
- 集成 OpenAI 智能决策助手
- 使用官方 tigeropen SDK（2025-12-24 更新）

## 📚 相关文档

- [Tiger 集成（行情/券商接口）](docs/Integrations/Tiger.md) - Tiger Open API 配置和使用说明
- [Tiger Open API 官方文档](https://quant.itigerup.com/openapi/zh/python/) - 完整的 SDK 文档
- [配置示例](.env.example) - 环境变量配置模板

## 📄 许可证

本项目仅供学习和研究使用。

---

**开发者**: AI Trading Team  
**最后更新**: 2025-12-24
