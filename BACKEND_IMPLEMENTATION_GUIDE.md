# 持仓评估与宏观风险分析 - 后端实现指南

## 已完成的架构

### 1. 数据库层 ✅
- **模型文件**：
  - `app/models/position_score.py` - 持仓评分模型
  - `app/models/technical_indicator.py` - 技术指标模型
  - `app/models/fundamental_data.py` - 基本面数据模型
  - `app/models/macro_risk.py` - 宏观风险模型

- **数据库表**：已通过 `create_position_macro_tables.py` 创建6个表

### 2. Schema层 ✅
- `app/schemas/position_assessment.py` - 持仓评估相关DTO
- `app/schemas/macro_risk.py` - 宏观风险相关DTO

### 3. 数据提供者层 ✅
- `app/providers/market_data_provider.py` - 市场数据提供者（yfinance）
- `app/providers/technical_calculator.py` - 技术指标计算引擎

### 4. 服务层（部分完成）
- `app/services/technical_analysis_service.py` - 技术分析服务 ✅

### 5. API层 ✅
- `app/routers/position_macro.py` - 持仓与宏观风险API端点
- 已注册到 `app/main.py`

---

## 需要安装的依赖包

```bash
# 进入项目目录
cd /Users/admin/IdeaProjects/ai_trading_backend_v8/backend

# 安装新依赖
pip install yfinance pandas-ta fredapi newsapi-python openai apscheduler
```

### 依赖说明：
- `yfinance` - 获取股票市场数据
- `pandas-ta` - 技术指标计算库
- `fredapi` - 美联储经济数据API
- `newsapi-python` - 新闻数据API
- `openai` - GPT-4 AI分析
- `apscheduler` - 定时任务调度

---

## 待实现的核心Service

### 1. 基本面分析服务
**文件**: `app/services/fundamental_analysis_service.py`

**功能**:
- 从yfinance/FMP获取财务数据
- 计算估值指标（PE/PB/PS/PEG）
- 计算盈利能力（ROE/毛利率）
- 计算成长性（营收增长）
- 评估财务健康度
- 生成基本面评分和总结

### 2. 持仓评分服务
**文件**: `app/services/position_scoring_service.py`

**功能**:
- 整合技术面、基本面、情绪面评分
- 计算综合评分（加权平均）
- 生成持仓建议（BUY/HOLD/REDUCE/SELL）
- 计算目标仓位、止损止盈
- 识别风险预警

### 3. 宏观指标服务
**文件**: `app/services/macro_indicators_service.py`

**功能**:
- 从FRED API获取经济数据
- 货币政策指标（利率、M2、通胀）
- 经济周期指标（GDP、失业率、PMI）
- 市场情绪指标（VIX、Put/Call Ratio）
- 缓存和定时更新

### 4. 宏观风险评分服务
**文件**: `app/services/macro_risk_scoring_service.py`

**功能**:
- 货币政策风险评分
- 地缘政治风险评分
- 行业泡沫风险评分
- 经济周期风险评分
- 市场情绪风险评分
- 综合风险评分和等级判断

### 5. 地缘政治事件服务
**文件**: `app/services/geopolitical_events_service.py`

**功能**:
- 从新闻API抓取地缘政治事件
- 事件分类和严重程度评估
- 影响行业识别
- 市场影响评分
- GPT-4事件解读

### 6. AI分析服务
**文件**: `app/services/ai_analysis_service.py`

**功能**:
- GPT-4技术面总结生成
- GPT-4基本面解读
- GPT-4宏观风险分析
- GPT-4投资建议生成

---

## 实施步骤

### Phase 1: 完成核心Service层（第1-2周）

#### Week 1: 技术面和基本面
```bash
# 1. 安装依赖
pip install yfinance pandas-ta

# 2. 测试技术分析服务
python -c "
from app.services.technical_analysis_service import TechnicalAnalysisService
# 测试代码
"

# 3. 实现基本面分析服务
# 创建 app/services/fundamental_analysis_service.py
# 参考 technical_analysis_service.py 的结构
```

**任务清单**:
- [ ] 完善 `TechnicalAnalysisService`
- [ ] 实现 `FundamentalAnalysisService`
- [ ] 实现 `PositionScoringService`
- [ ] 单元测试

#### Week 2: 宏观风险分析
```bash
# 1. 注册FRED API Key
# https://fred.stlouisfed.org/docs/api/api_key.html

# 2. 在 .env 中添加
FRED_API_KEY=your_fred_api_key_here
NEWS_API_KEY=your_newsapi_key_here
OPENAI_API_KEY=your_openai_key_here

# 3. 实现宏观服务
```

**任务清单**:
- [ ] 实现 `MacroIndicatorsService`
- [ ] 实现 `MacroRiskScoringService`
- [ ] 实现 `GeopoliticalEventsService`
- [ ] 实现 `AIAnalysisService`
- [ ] 单元测试

### Phase 2: 完善API端点（第3周）

**任务清单**:
- [ ] 实现 `GET /api/v1/positions/assessment`
- [ ] 实现 `GET /api/v1/positions/{symbol}/fundamental`
- [ ] 实现 `POST /api/v1/positions/refresh`
- [ ] 实现 `GET /api/v1/macro/risk/overview`
- [ ] 实现 `GET /api/v1/macro/monetary-policy`
- [ ] 实现 `GET /api/v1/macro/geopolitical-events`
- [ ] 实现 `POST /api/v1/macro/refresh`
- [ ] API文档完善（Swagger）

### Phase 3: 定时任务和缓存优化（第4周）

```python
# app/jobs/data_refresh_job.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# 每天早上9点刷新宏观数据
@scheduler.scheduled_job('cron', hour=9, minute=0)
async def refresh_macro_data():
    # 刷新FRED数据
    # 刷新新闻事件
    pass

# 每小时刷新技术指标
@scheduler.scheduled_job('interval', hours=1)
async def refresh_technical_indicators():
    # 刷新活跃标的的技术指标
    pass

scheduler.start()
```

**任务清单**:
- [ ] 实现定时任务调度
- [ ] 优化数据缓存策略
- [ ] 添加Redis缓存（可选）
- [ ] 性能测试和优化

### Phase 4: 前端集成和测试（第5周）

**任务清单**:
- [ ] API联调测试
- [ ] 错误处理和日志
- [ ] 性能监控
- [ ] 用户验收测试

---

## 测试API

### 1. 技术分析
```bash
curl -X GET "http://localhost:8088/api/v1/positions/AAPL/technical?timeframe=1D"
```

### 2. 基本面分析
```bash
curl -X GET "http://localhost:8088/api/v1/positions/AAPL/fundamental"
```

### 3. 持仓评估
```bash
curl -X GET "http://localhost:8088/api/v1/positions/assessment?window_days=7"
```

### 4. 宏观风险概览
```bash
curl -X GET "http://localhost:8088/api/v1/macro/risk/overview"
```

---

## 数据流架构

```
┌─────────────────┐
│  外部数据源      │
│  - yfinance     │
│  - FRED API     │
│  - News API     │
│  - Tiger API    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  数据提供者层    │
│  - MarketData   │
│  - MacroData    │
│  - NewsData     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  计算引擎层      │
│  - Technical    │
│  - Fundamental  │
│  - MacroRisk    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  服务层         │
│  - Analysis     │
│  - Scoring      │
│  - AI Summary   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  数据库缓存      │
│  - SQLite       │
│  - Redis(可选)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  API层          │
│  - FastAPI      │
│  - REST         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  前端展示        │
│  - Dashboard    │
│  - Charts       │
└─────────────────┘
```

---

## 关键设计决策

### 1. 缓存策略
- **技术指标**: 每小时更新，日内使用缓存
- **基本面数据**: 每天更新，季报时强制刷新
- **宏观指标**: 每天更新一次
- **新闻事件**: 每4小时抓取一次

### 2. 评分算法
- **技术面**: RSI(20%) + MACD(20%) + 趋势(30%) + 布林带(15%) + 成交量(15%)
- **基本面**: 估值(25%) + 盈利(25%) + 成长(25%) + 财务健康(25%)
- **情绪面**: 社交媒体(40%) + 资金流向(30%) + 期权数据(30%)
- **综合**: 技术(40%) + 基本面(40%) + 情绪(20%)

### 3. 风险等级划分
- **80-100分**: LOW RISK（低风险）
- **60-79分**: MEDIUM RISK（中等风险）
- **40-59分**: HIGH RISK（高风险）
- **0-39分**: EXTREME RISK（极端风险）

---

## 下一步行动

1. **立即执行**: 
   ```bash
   pip install yfinance pandas-ta
   ```

2. **测试技术分析服务**:
   ```bash
   cd backend
   python -c "
   import asyncio
   from app.services.technical_analysis_service import TechnicalAnalysisService
   from app.main import SessionLocal
   
   async def test():
       async with SessionLocal() as session:
           svc = TechnicalAnalysisService(session)
           result = await svc.get_technical_analysis('AAPL')
           print(result.dict())
   
   asyncio.run(test())
   "
   ```

3. **开始实现基本面服务**

---

**准备开始实施了吗？** 🚀
