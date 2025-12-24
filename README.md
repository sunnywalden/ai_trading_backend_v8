# AI Trading Backend V8

## 🎯 项目简介

AI Trading Backend V8 是一个**智能期权交易风险管理与自动对冲系统**，基于 FastAPI 构建。该系统结合了：

- **智能风险控制**：实时监控 Greeks 敞口（Delta、Gamma、Vega、Theta），设置多层级风险限额
- **交易行为分析**：基于历史成交数据分析交易者行为模式（卖飞、过度交易、报复性交易等）
- **自动对冲引擎**：根据风险状态自动生成最优对冲方案并执行订单
- **AI 决策助手**：集成 GPT-5.1，基于当前账户状态、风险敞口和行为画像提供智能交易建议

## 🏗️ 系统架构

```
backend/
├── app/
│   ├── main.py                    # FastAPI 主应用入口
│   ├── broker/                    # 券商接口层
│   │   ├── factory.py            # 券商客户端工厂（Tiger/Dummy）
│   │   ├── tiger_option_client.py      # Tiger 期权客户端
│   │   ├── tiger_trade_history_client.py # Tiger 历史成交客户端
│   │   ├── dummy_option_client.py      # 模拟客户端（用于测试）
│   │   └── models.py             # 券商数据模型
│   ├── core/                     # 核心配置
│   │   ├── config.py             # 应用配置（交易模式、API Key 等）
│   │   ├── trade_mode.py         # 交易模式枚举（OFF/DRY_RUN/REAL）
│   │   └── order_intent.py       # 订单意图定义
│   ├── engine/                   # 交易引擎
│   │   └── auto_hedge_engine.py  # 自动对冲引擎核心逻辑
│   ├── models/                   # 数据库模型
│   │   ├── db.py                 # 数据库基础配置
│   │   ├── symbol_behavior_stats.py    # 交易行为统计表
│   │   └── symbol_risk_profile.py      # 标的风险配置表
│   ├── services/                 # 业务服务层
│   │   ├── ai_advice_service.py         # AI 决策助手服务
│   │   ├── behavior_scoring_service.py  # 行为评分引擎
│   │   ├── hedge_advisor_service.py     # 对冲建议服务
│   │   ├── hedge_cost_service.py        # 对冲成本评估
│   │   ├── option_exposure_service.py   # Greeks 敞口计算
│   │   ├── risk_config_service.py       # 风险配置管理
│   │   ├── safety_guard.py              # 安全防护层
│   │   └── risk_event_logger.py         # 风险事件日志
│   ├── schemas/                  # API 数据模型
│   │   ├── ai_advice.py          # AI 建议请求/响应模型
│   │   └── ai_state.py           # 系统状态视图模型
│   └── jobs/                     # 定时任务
│       └── behavior_rebuild_job.py      # 行为评分重算任务
└── requirements.txt              # Python 依赖
```

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

集成 GPT-5.1 模型，提供智能交易建议：

- **输入**：交易目标、风险偏好、时间维度
- **分析**：自动聚合账户状态、Greeks 敞口、行为画像
- **输出**：结构化的交易建议、具体订单草案、风险提示

## 📡 API 接口

### 健康检查

```bash
GET /health
```

返回系统状态和当前交易模式。

### 获取系统状态

```bash
GET /ai/state
```

返回完整的系统状态视图：
- 当前交易模式
- 风险限额配置
- Greeks 敞口详情
- 各标的行为画像和评分

### 手动触发对冲

```bash
POST /run-auto-hedge-once
```

立即执行一次自动对冲流程。

### AI 决策建议

```bash
POST /ai/advice
Content-Type: application/json

{
  "objective": "控制 gamma 敞口",
  "risk_preference": "conservative",
  "time_horizon": "short_term"
}
```

返回 AI 生成的交易建议和订单草案。

### 重算行为评分

```bash
POST /admin/behavior/rebuild
Content-Type: application/json

{
  "account_id": "demo-account",
  "window_days": 60
}
```

基于最近 N 天的历史成交数据重新计算行为评分。

## ⚙️ 配置说明

在项目根目录创建 `.env` 文件：

```env
# 应用名称
APP_NAME="AI Trading Risk & Auto-Hedge Demo"

# 交易模式：OFF（关闭）/ DRY_RUN（模拟）/ REAL（实盘）
TRADE_MODE=DRY_RUN

# Tiger 券商账户
TIGER_ACCOUNT=demo-account

# Tiger Open API 配置（使用官方 tigeropen SDK）
# 留空则使用 Dummy 客户端（测试模式）
TIGER_PRIVATE_KEY_PATH=/path/to/your_private_key.pem
TIGER_ID=your_tiger_id

# 行情数据模式（可选）
# DELAYED: 免费延迟行情（15-20分钟延迟）- 开发测试
# REALTIME: 实时行情（需付费）- 生产环境
TIGER_QUOTE_MODE=DELAYED

# OpenAI 配置（用于 AI 决策助手）
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-5.1
```

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

详细评估报告：[QUOTE_DATA_ANALYSIS.md](QUOTE_DATA_ANALYSIS.md)

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
cd backend
pip install -r requirements.txt
```

### 配置 Tiger API（可选）

如需连接真实 Tiger API，请参考 [TIGER_API_GUIDE.md](TIGER_API_GUIDE.md) 完成配置。

不配置 Tiger API 时系统将使用 Dummy 客户端（测试模式）。

### 测试 API 连接

```bash
# 运行测试脚本验证配置
python test_tiger_api.py
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

访问 API 文档：http://localhost:8000/docs

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

## 🔧 技术栈

- **Web 框架**：FastAPI
- **异步 ORM**：SQLAlchemy (async)
- **数据库**：SQLite (aiosqlite)
- **数据验证**：Pydantic
- **AI 模型**：OpenAI GPT-5.1
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
- 集成 GPT-5.1 智能决策助手
- 使用官方 tigeropen SDK（2025-12-24 更新）

## 📚 相关文档

- [Tiger API 集成指南](TIGER_API_GUIDE.md) - Tiger Open API 配置和使用说明
- [Tiger Open API 官方文档](https://quant.itigerup.com/openapi/zh/python/) - 完整的 SDK 文档
- [配置示例](.env.example) - 环境变量配置模板

## 📄 许可证

本项目仅供学习和研究使用。

---

**开发者**: AI Trading Team  
**最后更新**: 2025-12-24
