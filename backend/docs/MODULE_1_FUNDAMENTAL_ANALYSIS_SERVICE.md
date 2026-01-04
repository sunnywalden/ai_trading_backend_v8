# 模块1: 基本面分析服务设计

## 1. 服务概述

### 职责
- 获取和计算股票基本面数据
- 评估公司估值水平
- 分析盈利能力和成长性
- 评估财务健康状况
- 生成基本面综合评分

### 依赖
- `app.providers.market_data_provider.MarketDataProvider` - 数据获取
- `app.models.fundamental_data.FundamentalData` - 数据模型
- `app.schemas.position_assessment.FundamentalAnalysisDTO` - 响应DTO

---

## 2. 类设计

### 2.1 服务类结构

```python
# app/services/fundamental_analysis_service.py

from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.fundamental_data import FundamentalData
from app.providers.market_data_provider import MarketDataProvider
from app.schemas.position_assessment import (
    FundamentalAnalysisDTO,
    ValuationMetricsDTO,
    ProfitabilityMetricsDTO,
    GrowthMetricsDTO,
    FinancialHealthDTO
)

class FundamentalAnalysisService:
    """基本面分析服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.market_data = MarketDataProvider()
        self.cache_duration = timedelta(days=1)  # 基本面数据每天更新一次
    
    async def get_fundamental_analysis(
        self,
        symbol: str,
        use_cache: bool = True
    ) -> FundamentalAnalysisDTO:
        """获取基本面分析（主入口）"""
        pass
    
    async def _get_cached_data(
        self,
        symbol: str
    ) -> Optional[FundamentalData]:
        """从数据库获取缓存的基本面数据"""
        pass
    
    async def _fetch_and_calculate(
        self,
        symbol: str
    ) -> FundamentalData:
        """从市场获取数据并计算指标"""
        pass
    
    async def _save_to_cache(
        self,
        data: FundamentalData
    ) -> None:
        """保存基本面数据到数据库缓存"""
        pass
    
    def _calculate_valuation_score(
        self,
        pe_ratio: Optional[float],
        pb_ratio: Optional[float],
        ps_ratio: Optional[float],
        peg_ratio: Optional[float],
        industry_avg_pe: Optional[float] = None
    ) -> float:
        """计算估值评分 (0-100)"""
        pass
    
    def _calculate_profitability_score(
        self,
        roe: Optional[float],
        roa: Optional[float],
        gross_margin: Optional[float],
        operating_margin: Optional[float],
        net_margin: Optional[float]
    ) -> float:
        """计算盈利能力评分 (0-100)"""
        pass
    
    def _calculate_growth_score(
        self,
        revenue_growth: Optional[float],
        earnings_growth: Optional[float],
        eps_growth: Optional[float]
    ) -> float:
        """计算成长性评分 (0-100)"""
        pass
    
    def _calculate_health_score(
        self,
        current_ratio: Optional[float],
        quick_ratio: Optional[float],
        debt_to_equity: Optional[float],
        interest_coverage: Optional[float]
    ) -> float:
        """计算财务健康度评分 (0-100)"""
        pass
    
    def _calculate_overall_score(
        self,
        valuation_score: float,
        profitability_score: float,
        growth_score: float,
        health_score: float
    ) -> float:
        """计算基本面综合评分"""
        # 权重: 估值25% + 盈利25% + 成长25% + 健康25%
        pass
    
    def _generate_summary(
        self,
        symbol: str,
        overall_score: float,
        valuation_score: float,
        profitability_score: float,
        growth_score: float,
        health_score: float
    ) -> str:
        """生成基本面分析总结"""
        pass
```

---

## 3. 数据获取设计

### 3.1 数据源
使用 `yfinance` 获取以下数据：

```python
# 从 MarketDataProvider 获取
financials = await self.market_data.get_financials(symbol)
key_stats = await self.market_data.get_key_statistics(symbol)
info = await self.market_data.get_company_info(symbol)
```

### 3.2 需要的财务指标

#### 估值指标
- **PE Ratio**: `info.get('trailingPE')` or `info.get('forwardPE')`
- **PB Ratio**: `info.get('priceToBook')`
- **PS Ratio**: `info.get('priceToSalesTrailing12Months')`
- **PEG Ratio**: `info.get('pegRatio')`

#### 盈利能力指标
- **ROE**: `info.get('returnOnEquity')` * 100
- **ROA**: `info.get('returnOnAssets')` * 100
- **Gross Margin**: `info.get('grossMargins')` * 100
- **Operating Margin**: `info.get('operatingMargins')` * 100
- **Net Margin**: `info.get('profitMargins')` * 100

#### 成长性指标
- **Revenue Growth**: `info.get('revenueGrowth')` * 100
- **Earnings Growth**: `info.get('earningsGrowth')` * 100
- **EPS Growth**: 计算最近4个季度EPS增长率

#### 财务健康指标
- **Current Ratio**: `info.get('currentRatio')`
- **Quick Ratio**: `info.get('quickRatio')`
- **Debt to Equity**: `info.get('debtToEquity')`
- **Interest Coverage**: EBIT / Interest Expense

---

## 4. 评分算法设计

### 4.1 估值评分 (0-100分)

```python
def _calculate_valuation_score(self, pe_ratio, pb_ratio, ps_ratio, peg_ratio, industry_avg_pe=None):
    """
    估值评分规则:
    - PE Ratio: 越低越好
      - < 10: 100分
      - 10-15: 80分
      - 15-25: 60分
      - 25-35: 40分
      - > 35: 20分
    
    - PB Ratio: 越低越好
      - < 1: 100分
      - 1-2: 80分
      - 2-3: 60分
      - 3-5: 40分
      - > 5: 20分
    
    - PEG Ratio: < 1 为理想
      - < 0.5: 100分
      - 0.5-1: 80分
      - 1-1.5: 60分
      - 1.5-2: 40分
      - > 2: 20分
    
    综合得分 = PE权重40% + PB权重30% + PEG权重30%
    """
    scores = []
    weights = []
    
    if pe_ratio:
        if pe_ratio < 10:
            pe_score = 100
        elif pe_ratio < 15:
            pe_score = 80
        elif pe_ratio < 25:
            pe_score = 60
        elif pe_ratio < 35:
            pe_score = 40
        else:
            pe_score = 20
        scores.append(pe_score)
        weights.append(0.4)
    
    if pb_ratio:
        if pb_ratio < 1:
            pb_score = 100
        elif pb_ratio < 2:
            pb_score = 80
        elif pb_ratio < 3:
            pb_score = 60
        elif pb_ratio < 5:
            pb_score = 40
        else:
            pb_score = 20
        scores.append(pb_score)
        weights.append(0.3)
    
    if peg_ratio:
        if peg_ratio < 0.5:
            peg_score = 100
        elif peg_ratio < 1:
            peg_score = 80
        elif peg_ratio < 1.5:
            peg_score = 60
        elif peg_ratio < 2:
            peg_score = 40
        else:
            peg_score = 20
        scores.append(peg_score)
        weights.append(0.3)
    
    if not scores:
        return 50.0  # 默认中性分数
    
    # 加权平均
    total_weight = sum(weights)
    weighted_sum = sum(s * w for s, w in zip(scores, weights))
    return weighted_sum / total_weight
```

### 4.2 盈利能力评分 (0-100分)

```python
def _calculate_profitability_score(self, roe, roa, gross_margin, operating_margin, net_margin):
    """
    盈利能力评分规则:
    
    - ROE (净资产收益率):
      - > 20%: 100分
      - 15-20%: 80分
      - 10-15%: 60分
      - 5-10%: 40分
      - < 5%: 20分
    
    - ROA (总资产收益率):
      - > 10%: 100分
      - 7-10%: 80分
      - 5-7%: 60分
      - 3-5%: 40分
      - < 3%: 20分
    
    - Gross Margin (毛利率):
      - > 50%: 100分
      - 40-50%: 80分
      - 30-40%: 60分
      - 20-30%: 40分
      - < 20%: 20分
    
    - Net Margin (净利率):
      - > 20%: 100分
      - 15-20%: 80分
      - 10-15%: 60分
      - 5-10%: 40分
      - < 5%: 20分
    
    综合得分 = ROE 30% + ROA 20% + 毛利率 25% + 净利率 25%
    """
    # 实现逻辑同估值评分
```

### 4.3 成长性评分 (0-100分)

```python
def _calculate_growth_score(self, revenue_growth, earnings_growth, eps_growth):
    """
    成长性评分规则:
    
    - Revenue Growth (营收增长率):
      - > 30%: 100分
      - 20-30%: 80分
      - 10-20%: 60分
      - 0-10%: 40分
      - < 0%: 20分
    
    - Earnings Growth (盈利增长率):
      - > 30%: 100分
      - 20-30%: 80分
      - 10-20%: 60分
      - 0-10%: 40分
      - < 0%: 20分
    
    综合得分 = 营收增长 40% + 盈利增长 40% + EPS增长 20%
    """
```

### 4.4 财务健康度评分 (0-100分)

```python
def _calculate_health_score(self, current_ratio, quick_ratio, debt_to_equity, interest_coverage):
    """
    财务健康度评分规则:
    
    - Current Ratio (流动比率):
      - > 2: 100分
      - 1.5-2: 80分
      - 1-1.5: 60分
      - 0.5-1: 40分
      - < 0.5: 20分
    
    - Quick Ratio (速动比率):
      - > 1.5: 100分
      - 1-1.5: 80分
      - 0.8-1: 60分
      - 0.5-0.8: 40分
      - < 0.5: 20分
    
    - Debt to Equity (资产负债率):
      - < 0.3: 100分 (低负债)
      - 0.3-0.5: 80分
      - 0.5-1: 60分
      - 1-1.5: 40分
      - > 1.5: 20分 (高负债)
    
    - Interest Coverage (利息保障倍数):
      - > 10: 100分
      - 5-10: 80分
      - 3-5: 60分
      - 1-3: 40分
      - < 1: 20分
    
    综合得分 = 流动比率 25% + 速动比率 25% + 资产负债率 25% + 利息保障 25%
    """
```

---

## 5. 缓存策略

### 5.1 缓存逻辑
```python
async def get_fundamental_analysis(self, symbol: str, use_cache: bool = True):
    # 1. 尝试从缓存获取
    if use_cache:
        cached = await self._get_cached_data(symbol)
        if cached and (datetime.utcnow() - cached.timestamp) < self.cache_duration:
            return self._build_dto(cached)
    
    # 2. 缓存未命中，从市场获取
    data = await self._fetch_and_calculate(symbol)
    
    # 3. 保存到缓存
    await self._save_to_cache(data)
    
    # 4. 返回DTO
    return self._build_dto(data)
```

### 5.2 缓存失效时机
- **时间**: 每天更新一次（财务数据变化慢）
- **事件**: 季报发布后强制刷新
- **手动**: 用户可手动触发刷新

---

## 6. 数据库交互

### 6.1 查询缓存
```python
async def _get_cached_data(self, symbol: str) -> Optional[FundamentalData]:
    stmt = select(FundamentalData).where(
        FundamentalData.symbol == symbol
    ).order_by(FundamentalData.timestamp.desc()).limit(1)
    
    result = await self.session.execute(stmt)
    return result.scalar_one_or_none()
```

### 6.2 保存数据
```python
async def _save_to_cache(self, data: FundamentalData):
    self.session.add(data)
    await self.session.commit()
    await self.session.refresh(data)
```

---

## 7. 响应构建

### 7.1 DTO映射
```python
def _build_dto(self, data: FundamentalData) -> FundamentalAnalysisDTO:
    return FundamentalAnalysisDTO(
        valuation=ValuationMetricsDTO(
            pe_ratio=data.pe_ratio,
            pb_ratio=data.pb_ratio,
            ps_ratio=data.ps_ratio,
            peg_ratio=data.peg_ratio,
            score=data.valuation_score
        ),
        profitability=ProfitabilityMetricsDTO(
            roe=data.roe,
            roa=data.roa,
            gross_margin=data.gross_margin,
            operating_margin=data.operating_margin,
            net_margin=data.net_margin,
            score=data.profitability_score
        ),
        growth=GrowthMetricsDTO(
            revenue_growth=data.revenue_growth,
            earnings_growth=data.earnings_growth,
            eps_growth=data.eps_growth,
            score=data.growth_score
        ),
        financial_health=FinancialHealthDTO(
            current_ratio=data.current_ratio,
            quick_ratio=data.quick_ratio,
            debt_to_equity=data.debt_to_equity,
            interest_coverage=data.interest_coverage,
            score=data.health_score
        ),
        overall_score=data.overall_score,
        timestamp=data.timestamp,
        summary=data.ai_summary or self._generate_summary(...)
    )
```

---

## 8. 错误处理

### 8.1 数据缺失处理
```python
# 当某些指标缺失时，使用剩余指标计算评分
# 例如：如果PEG不可用，只用PE和PB计算估值分数
if not peg_ratio:
    # 重新分配权重: PE 60%, PB 40%
    pass
```

### 8.2 异常处理
```python
try:
    info = await self.market_data.get_company_info(symbol)
except Exception as e:
    # 记录日志
    logger.error(f"Failed to fetch data for {symbol}: {e}")
    # 返回默认值或抛出自定义异常
    raise AnalysisError(f"无法获取{symbol}的基本面数据")
```

---

## 9. AI总结生成

### 9.1 规则引擎总结（简化版）
```python
def _generate_summary(self, symbol, overall_score, valuation_score, profitability_score, growth_score, health_score):
    """基于规则生成基本面总结"""
    
    summary_parts = []
    
    # 综合评价
    if overall_score >= 80:
        summary_parts.append(f"{symbol}基本面优秀")
    elif overall_score >= 60:
        summary_parts.append(f"{symbol}基本面良好")
    elif overall_score >= 40:
        summary_parts.append(f"{symbol}基本面中等")
    else:
        summary_parts.append(f"{symbol}基本面较弱")
    
    # 估值评价
    if valuation_score >= 70:
        summary_parts.append("估值偏低，具有投资价值")
    elif valuation_score < 40:
        summary_parts.append("估值偏高，谨慎追高")
    
    # 盈利能力
    if profitability_score >= 70:
        summary_parts.append("盈利能力强劲")
    elif profitability_score < 40:
        summary_parts.append("盈利能力待改善")
    
    # 成长性
    if growth_score >= 70:
        summary_parts.append("成长性良好")
    elif growth_score < 40:
        summary_parts.append("增长放缓")
    
    # 财务健康
    if health_score >= 70:
        summary_parts.append("财务状况健康")
    elif health_score < 40:
        summary_parts.append("财务风险较高")
    
    return "；".join(summary_parts) + "。"
```

### 9.2 GPT-4增强版（可选）
```python
async def _generate_ai_summary(self, data: FundamentalData):
    """使用GPT-4生成深度分析"""
    from app.services.ai_analysis_service import AIAnalysisService
    
    ai_service = AIAnalysisService()
    prompt = f"""
    分析{data.symbol}的基本面数据：
    - 估值: PE={data.pe_ratio}, PB={data.pb_ratio}, PEG={data.peg_ratio}
    - 盈利: ROE={data.roe}%, 净利率={data.net_margin}%
    - 成长: 营收增长={data.revenue_growth}%, 盈利增长={data.earnings_growth}%
    - 健康: 流动比率={data.current_ratio}, 资产负债率={data.debt_to_equity}
    
    请给出专业的投资分析建议（100字以内）。
    """
    return await ai_service.generate_summary(prompt)
```

---

## 10. 性能优化

### 10.1 批量查询优化
```python
async def batch_analyze(self, symbols: list[str]) -> dict[str, FundamentalAnalysisDTO]:
    """批量分析多个标的"""
    # 1. 批量查询缓存
    cached = await self._batch_get_cached(symbols)
    
    # 2. 识别需要刷新的标的
    to_fetch = [s for s in symbols if s not in cached or self._is_stale(cached[s])]
    
    # 3. 并发获取市场数据
    tasks = [self._fetch_and_calculate(s) for s in to_fetch]
    fresh_data = await asyncio.gather(*tasks)
    
    # 4. 合并结果
    results = {**cached, **{d.symbol: d for d in fresh_data}}
    return {s: self._build_dto(results[s]) for s in symbols}
```

---

## 11. 测试用例

### 11.1 单元测试
```python
@pytest.mark.asyncio
async def test_calculate_valuation_score():
    service = FundamentalAnalysisService(mock_session)
    
    # 测试优秀估值
    score = service._calculate_valuation_score(
        pe_ratio=12, pb_ratio=1.5, ps_ratio=2, peg_ratio=0.8
    )
    assert score >= 70
    
    # 测试高估值
    score = service._calculate_valuation_score(
        pe_ratio=50, pb_ratio=8, ps_ratio=10, peg_ratio=3
    )
    assert score < 40
```

### 11.2 集成测试
```python
@pytest.mark.asyncio
async def test_get_fundamental_analysis():
    async with AsyncSession() as session:
        service = FundamentalAnalysisService(session)
        result = await service.get_fundamental_analysis("AAPL")
        
        assert result.overall_score >= 0
        assert result.overall_score <= 100
        assert result.valuation is not None
        assert result.profitability is not None
```

---

## 12. 实现检查清单

- [ ] 创建 `app/services/fundamental_analysis_service.py`
- [ ] 实现所有方法签名
- [ ] 实现4个评分算法
- [ ] 实现缓存读写逻辑
- [ ] 实现DTO构建
- [ ] 添加错误处理
- [ ] 编写单元测试
- [ ] 编写文档字符串
- [ ] 性能测试（单次查询 < 500ms）
- [ ] 集成到API端点

---

**预计工作量**: 8-10小时
**优先级**: P0 (核心功能)
**依赖**: MarketDataProvider, FundamentalData模型
