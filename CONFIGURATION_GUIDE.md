# 配置指南

## 环境变量配置

### 必需配置

这些配置是系统运行的基本要求：

```bash
# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///./demo.db

# 交易模式（REAL=实盘, PAPER=模拟盘）
TRADE_MODE=REAL
```

### 可选配置

这些配置可以增强系统功能，但不配置也能运行（有降级策略）：

#### 1. OpenAI API 配置（AI分析功能）

**用途**: 生成智能化的技术面、基本面和宏观分析摘要

**获取方式**: 
- 访问 https://platform.openai.com/api-keys
- 注册账号并创建API密钥

**配置**:
```bash
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**降级策略**: 
- 未配置时，系统使用规则引擎生成分析摘要
- AI摘要质量更高、更个性化，但规则引擎也能提供基础分析

**网络要求**:
- 需要能访问 `https://api.openai.com`
- 中国大陆可能需要配置代理
- 可以配置国内镜像：
  ```bash
  OPENAI_API_BASE=https://your-proxy-url.com/v1
  ```

**常见错误**:
- `Connection error`: 网络连接问题，检查网络或配置代理
- `Authentication error`: API密钥无效或过期
- `Rate limit`: API调用频率超限，需要升级账户或降低调用频率

---

#### 2. FRED API 配置（宏观经济数据）

**用途**: 获取美联储经济数据（利率、GDP、失业率、通胀等）

**获取方式**:
- 访问 https://fred.stlouisfed.org/docs/api/api_key.html
- 免费注册即可获得API密钥

**配置**:
```bash
FRED_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**降级策略**:
- 未配置时，使用yfinance获取部分宏观数据
- 数据完整性会降低，但核心功能不受影响

---

#### 3. News API 配置（地缘政治事件）

**用途**: 获取全球新闻事件，用于地缘政治风险评估

**获取方式**:
- 访问 https://newsapi.org/register
- 免费账户每天100次请求

**配置**:
```bash
NEWS_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**降级策略**:
- 未配置时，地缘政治事件列表为空
- 宏观风险评分的地缘政治维度使用默认值（90分/低风险）

---

#### 4. Tiger Broker API（券商接口）

**用途**: 连接Tiger Broker获取实盘持仓和下单

**获取方式**:
- 开通Tiger Broker账户
- 在Tiger官网申请API权限

**配置**:
```bash
TIGER_CLIENT_ID=your_client_id
TIGER_PRIVATE_KEY=/path/to/your_private_key.pem
TIGER_ACCOUNT=your_account_id
```

**降级策略**:
- 未配置时，使用Dummy客户端（模拟数据）
- 可以正常运行和测试所有功能

---

## 缓存配置

调整数据缓存时间（单位：小时）：

```bash
# 技术指标缓存（默认1小时）
CACHE_TTL_TECHNICAL_HOURS=1

# 基本面数据缓存（默认24小时）
CACHE_TTL_FUNDAMENTAL_HOURS=24

# 宏观指标缓存（默认24小时）
CACHE_TTL_MACRO_HOURS=24
```

---

## 完整 .env 配置示例

### 最小配置（开发环境）

```bash
# 基础配置
DATABASE_URL=sqlite+aiosqlite:///./demo.db
TRADE_MODE=PAPER

# 缓存配置
CACHE_TTL_TECHNICAL_HOURS=1
CACHE_TTL_FUNDAMENTAL_HOURS=24
CACHE_TTL_MACRO_HOURS=24
```

### 完整配置（生产环境）

```bash
# ==================== 基础配置 ====================
DATABASE_URL=sqlite+aiosqlite:///./demo.db
TRADE_MODE=REAL

# ==================== API密钥 ====================
# OpenAI API（可选，用于AI分析）
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# FRED API（可选，用于宏观经济数据）
FRED_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# News API（可选，用于地缘政治事件）
NEWS_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Tiger Broker API（可选，用于实盘交易）
TIGER_CLIENT_ID=your_client_id
TIGER_PRIVATE_KEY=/path/to/private_key.pem
TIGER_ACCOUNT=your_account_id

# ==================== 缓存配置 ====================
CACHE_TTL_TECHNICAL_HOURS=1
CACHE_TTL_FUNDAMENTAL_HOURS=24
CACHE_TTL_MACRO_HOURS=24
```

---

## 配置验证

启动服务后，检查日志输出：

### ✅ 正常启动日志

```
INFO: OpenAI client initialized successfully
INFO: FRED API key configured
INFO: News API key configured
INFO: ✓ Scheduler started with 6 periodic tasks
INFO: Uvicorn running on http://0.0.0.0:8088
```

### ⚠️ 降级模式日志

```
WARNING: OPENAI_API_KEY not configured, AI analysis will use rule-based fallback
WARNING: FRED_API_KEY not configured, using yfinance for macro data
WARNING: NEWS_API_KEY not configured, geopolitical events will be unavailable
INFO: Using DummyOptionClient (Tiger API not configured)
```

这些警告不影响服务运行，只是某些功能使用降级策略。

---

## CORS配置

如果需要从前端（浏览器）调用API，已经配置了CORS中间件。

**开发环境**（当前配置）:
```python
allow_origins=["*"]  # 允许所有来源
```

**生产环境**（建议修改）:
```python
allow_origins=[
    "https://your-frontend-domain.com",
    "https://www.your-frontend-domain.com"
]
```

修改位置: `backend/app/main.py` 第44-51行

---

## 网络代理配置

如果在中国大陆使用OpenAI API，需要配置代理：

### 方法1: 环境变量

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

### 方法2: OpenAI配置（在代码中）

修改 `backend/app/services/ai_analysis_service.py`:

```python
from openai import AsyncOpenAI
import httpx

# 创建带代理的HTTP客户端
http_client = httpx.AsyncClient(
    proxies={
        "http://": "http://127.0.0.1:7890",
        "https://": "http://127.0.0.1:7890"
    }
)

_openai_client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY,
    http_client=http_client
)
```

### 方法3: 使用镜像站点

```bash
OPENAI_API_BASE=https://api.openai-proxy.com/v1
```

---

## 数据库配置

### SQLite（默认，开发环境）

```bash
DATABASE_URL=sqlite+aiosqlite:///./demo.db
```

**优点**: 零配置，适合开发和测试  
**缺点**: 并发性能有限

### PostgreSQL（推荐，生产环境）

```bash
DATABASE_URL=postgresql+asyncpg://username:password@localhost:5432/trading_db
```

**优点**: 高性能，适合生产环境  
**需要**: 
1. 安装依赖: `pip install asyncpg`
2. 安装PostgreSQL数据库

---

## 故障排查

### 问题1: OPTIONS请求405错误

**症状**: 前端调用API时报OPTIONS请求被拒绝

**解决**: ✅ 已修复，添加了CORS中间件

---

### 问题2: GPT连接失败

**症状**: 日志显示 "Failed to call gpt-4: Connection error"

**排查步骤**:
1. 检查 `.env` 中是否配置了 `OPENAI_API_KEY`
2. 验证API密钥是否有效：
   ```bash
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```
3. 检查网络连接是否可以访问 `api.openai.com`
4. 如果在中国大陆，配置代理或使用镜像

**临时方案**: 不配置OpenAI，系统会自动降级到规则引擎

---

### 问题3: FRED数据获取失败

**症状**: 宏观指标数据为空或使用默认值

**排查步骤**:
1. 检查 `FRED_API_KEY` 是否配置
2. 验证API密钥：访问 https://fred.stlouisfed.org/
3. 检查API调用次数是否超限（免费账户每天限额）

**临时方案**: 不配置FRED，系统会使用yfinance获取部分数据

---

### 问题4: 定时任务未执行

**症状**: 数据长时间不更新

**排查步骤**:
1. 检查调度器是否正常启动：
   ```bash
   curl http://localhost:8088/admin/scheduler/jobs
   ```
2. 查看日志是否有任务执行记录
3. 确认任务的下次执行时间

**手动触发**:
```bash
# 刷新持仓数据
curl -X POST http://localhost:8088/api/v1/positions/refresh

# 刷新宏观数据
curl -X POST http://localhost:8088/api/v1/macro/refresh
```

---

## 性能优化建议

### 1. 数据库优化

- 生产环境使用PostgreSQL
- 定期清理历史数据（已配置自动清理任务）
- 根据访问模式添加索引

### 2. 缓存优化

- 调整缓存TTL适应你的使用场景
- 技术指标更新频繁，TTL可以设置短一些
- 基本面数据变化慢，TTL可以设置长一些

### 3. API调用优化

- OpenAI: 控制调用频率，避免超限
- FRED: 缓存宏观数据，减少API调用
- News API: 注意每日请求限制（免费100次）

### 4. 并发配置

调整Uvicorn worker数量：

```bash
uvicorn app.main:app --workers 4 --host 0.0.0.0 --port 8088
```

---

## 安全建议

### 1. 生产环境必须做的事

- ✅ 限制CORS来源为特定域名
- ✅ 添加API认证（JWT Token或API Key）
- ✅ 配置HTTPS证书
- ✅ 设置请求限流（rate limiting）
- ✅ 敏感信息不要提交到Git

### 2. .gitignore配置

确保 `.env` 文件已加入 `.gitignore`:

```
.env
*.pem
*.key
demo.db
__pycache__/
*.pyc
```

### 3. 密钥管理

**开发环境**: 使用 `.env` 文件  
**生产环境**: 使用环境变量或密钥管理服务（如AWS Secrets Manager）

---

## 监控和日志

### 启用详细日志

修改 `backend/app/main.py`:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 日志级别

- `DEBUG`: 详细的调试信息
- `INFO`: 一般信息（默认）
- `WARNING`: 警告信息（不影响运行）
- `ERROR`: 错误信息（需要关注）

### 健康检查

定期检查服务状态：

```bash
# 健康检查
curl http://localhost:8088/health

# 检查定时任务
curl http://localhost:8088/admin/scheduler/jobs

# 检查数据更新时间（在响应的timestamp字段）
curl http://localhost:8088/api/v1/macro/risk/overview | jq '.timestamp'
```

---

## 联系支持

如有问题，请查看：
- 完整API文档: [API_DOCUMENTATION.md](API_DOCUMENTATION.md)
- 快速开始: [QUICKSTART.md](QUICKSTART.md)
- GitHub Issues: [项目地址]

---

**最后更新**: 2026-01-04
