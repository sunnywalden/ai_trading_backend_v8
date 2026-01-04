# 模块3: 宏观指标服务设计

## 1. 服务概述

### 职责
- 从FRED API获取宏观经济数据
- 计算和存储关键宏观指标
- 分析经济周期阶段
- 监测货币政策变化
- 追踪市场情绪指标

### 数据源
- **FRED (Federal Reserve Economic Data)** - 美联储经济数据
- **yfinance** - VIX、市场指数数据
- **Tiger API** - 市场数据补充

---

## 2. 类设计

### 2.1 服务类结构

```python
# app/services/macro_indicators_service.py

from typing import Optional, List, Dict
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fredapi import Fred
import yfinance as yf

from app.models.macro_risk import MacroIndicator
from app.core.config import settings
from app.schemas.macro_risk import (
    MonetaryPolicyDTO,
    EconomicCycleDTO,
    MarketSentimentDTO,
    MacroIndicatorValueDTO
)

class MacroIndicatorsService:
    """宏观指标服务"""
    
    # FRED数据系列ID映射
    FRED_SERIES = {
        # 货币政策指标
        "fed_funds_rate": "DFF",              # 联邦基金利率
        "10y_treasury": "DGS10",              # 10年期国债收益率
        "2y_treasury": "DGS2",                # 2年期国债收益率
        "m2_money_supply": "M2SL",            # M2货币供应量
        "cpi": "CPIAUCSL",                    # 消费者物价指数
        "core_cpi": "CPILFESL",               # 核心CPI
        "pce": "PCE",                         # 个人消费支出
        
        # 经济周期指标
        "gdp": "GDP",                         # GDP
        "gdp_growth": "A191RL1Q225SBEA",      # GDP增长率
        "unemployment": "UNRATE",             # 失业率
        "initial_claims": "ICSA",             # 初次申请失业金人数
        "manufacturing_pmi": "MANEMP",        # 制造业PMI
        "retail_sales": "RSXFS",              # 零售销售
        "housing_starts": "HOUST",            # 新屋开工
        "industrial_production": "INDPRO",    # 工业生产指数
        
        # 其他
        "consumer_sentiment": "UMCSENT",      # 密歇根消费者信心指数
    }
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.fred = Fred(api_key=settings.FRED_API_KEY)
        self.cache_duration = timedelta(hours=6)  # 宏观数据6小时更新一次
    
    async def get_monetary_policy(
        self,
        use_cache: bool = True
    ) -> MonetaryPolicyDTO:
        """获取货币政策指标"""
        pass
    
    async def get_economic_cycle(
        self,
        use_cache: bool = True
    ) -> EconomicCycleDTO:
        """获取经济周期指标"""
        pass
    
    async def get_market_sentiment(
        self,
        use_cache: bool = True
    ) -> MarketSentimentDTO:
        """获取市场情绪指标"""
        pass
    
    async def refresh_all_indicators(self) -> Dict[str, int]:
        """刷新所有宏观指标（定时任务调用）"""
        pass
    
    async def _fetch_fred_indicator(
        self,
        indicator_name: str,
        series_id: str,
        lookback_days: int = 365
    ) -> Optional[MacroIndicator]:
        """从FRED获取单个指标"""
        pass
    
    async def _get_cached_indicator(
        self,
        indicator_name: str
    ) -> Optional[MacroIndicator]:
        """从数据库获取缓存指标"""
        pass
    
    async def _save_indicator(
        self,
        indicator: MacroIndicator
    ) -> None:
        """保存指标到数据库"""
        pass
    
    def _calculate_yield_curve(
        self,
        two_year_yield: float,
        ten_year_yield: float
    ) -> float:
        """计算收益率曲线斜率"""
        pass
    
    def _analyze_monetary_policy_stance(
        self,
        fed_funds_rate: float,
        inflation_rate: float,
        m2_growth: float
    ) -> str:
        """分析货币政策立场（宽松/中性/紧缩）"""
        pass
    
    def _determine_economic_cycle_phase(
        self,
        gdp_growth: float,
        unemployment: float,
        pmi: float
    ) -> str:
        """判断经济周期阶段（扩张/繁荣/衰退/复苏）"""
        pass
    
    async def _fetch_vix(self) -> float:
        """获取VIX恐慌指数"""
        pass
    
    async def _calculate_put_call_ratio(self) -> float:
        """计算市场Put/Call比率"""
        pass
```

---

## 3. 数据获取设计

### 3.1 FRED API集成

```python
async def _fetch_fred_indicator(
    self,
    indicator_name: str,
    series_id: str,
    lookback_days: int = 365
) -> Optional[MacroIndicator]:
    """
    从FRED API获取指标数据
    
    参数:
        indicator_name: 指标名称（内部标识）
        series_id: FRED数据系列ID
        lookback_days: 回溯天数
    
    返回:
        MacroIndicator对象
    """
    try:
        # 获取历史数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        series = self.fred.get_series(
            series_id,
            observation_start=start_date,
            observation_end=end_date
        )
        
        if series.empty:
            return None
        
        # 获取最新值
        latest_value = float(series.iloc[-1])
        latest_date = series.index[-1]
        
        # 计算变化（月度、季度、年度）
        prev_month_value = series.iloc[-30] if len(series) >= 30 else series.iloc[0]
        prev_quarter_value = series.iloc[-90] if len(series) >= 90 else series.iloc[0]
        prev_year_value = series.iloc[-365] if len(series) >= 365 else series.iloc[0]
        
        change_1m = ((latest_value - prev_month_value) / prev_month_value * 100) if prev_month_value else 0
        change_3m = ((latest_value - prev_quarter_value) / prev_quarter_value * 100) if prev_quarter_value else 0
        change_1y = ((latest_value - prev_year_value) / prev_year_value * 100) if prev_year_value else 0
        
        # 创建MacroIndicator对象
        indicator = MacroIndicator(
            indicator_name=indicator_name,
            indicator_category="monetary_policy",  # 或 "economic_cycle"
            value=latest_value,
            change_1m=change_1m,
            change_3m=change_3m,
            change_1y=change_1y,
            unit=self._get_unit(indicator_name),
            data_source="FRED",
            timestamp=datetime.utcnow()
        )
        
        return indicator
        
    except Exception as e:
        logger.error(f"Failed to fetch {indicator_name} from FRED: {e}")
        return None

def _get_unit(self, indicator_name: str) -> str:
    """获取指标单位"""
    units = {
        "fed_funds_rate": "%",
        "10y_treasury": "%",
        "2y_treasury": "%",
        "cpi": "Index",
        "gdp": "Billions",
        "gdp_growth": "%",
        "unemployment": "%",
        "manufacturing_pmi": "Index",
        "vix": "Index",
    }
    return units.get(indicator_name, "")
```

### 3.2 市场情绪指标获取

```python
async def _fetch_vix(self) -> float:
    """
    获取VIX恐慌指数
    
    使用yfinance获取^VIX
    """
    try:
        vix = yf.Ticker("^VIX")
        data = vix.history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
        return None
    except Exception as e:
        logger.error(f"Failed to fetch VIX: {e}")
        return None

async def _calculate_put_call_ratio(self) -> float:
    """
    计算市场Put/Call比率
    
    使用CBOE数据或从期权成交量计算
    简化版：使用VIX作为代理
    """
    try:
        # TODO: 接入CBOE Put/Call数据
        # 暂时返回模拟值
        vix = await self._fetch_vix()
        if vix:
            # VIX越高，恐慌情绪越强，Put/Call比率越高
            # 正常范围: 0.7-1.3
            return round(0.8 + (vix - 15) / 50, 2)
        return 1.0
    except:
        return 1.0
```

---

## 4. 指标计算和分析

### 4.1 货币政策分析

```python
async def get_monetary_policy(self, use_cache: bool = True) -> MonetaryPolicyDTO:
    """
    获取货币政策指标
    
    包含:
    - 联邦基金利率
    - 10年期国债收益率
    - 2年期国债收益率
    - 收益率曲线（10Y-2Y）
    - M2货币供应量
    - CPI通胀率
    - 货币政策立场判断
    """
    
    # 1. 获取各项指标
    fed_funds = await self._get_or_fetch_indicator("fed_funds_rate")
    treasury_10y = await self._get_or_fetch_indicator("10y_treasury")
    treasury_2y = await self._get_or_fetch_indicator("2y_treasury")
    m2 = await self._get_or_fetch_indicator("m2_money_supply")
    cpi = await self._get_or_fetch_indicator("cpi")
    
    # 2. 计算衍生指标
    yield_curve = self._calculate_yield_curve(
        treasury_2y.value if treasury_2y else 0,
        treasury_10y.value if treasury_10y else 0
    )
    
    # 3. 判断货币政策立场
    stance = self._analyze_monetary_policy_stance(
        fed_funds.value if fed_funds else 0,
        cpi.change_1y if cpi else 0,
        m2.change_1y if m2 else 0
    )
    
    # 4. 构建DTO
    return MonetaryPolicyDTO(
        fed_funds_rate=MacroIndicatorValueDTO(
            value=fed_funds.value if fed_funds else None,
            change_1m=fed_funds.change_1m if fed_funds else None,
            change_1y=fed_funds.change_1y if fed_funds else None,
            unit="%"
        ),
        treasury_10y=MacroIndicatorValueDTO(
            value=treasury_10y.value if treasury_10y else None,
            change_1m=treasury_10y.change_1m if treasury_10y else None,
            change_1y=treasury_10y.change_1y if treasury_10y else None,
            unit="%"
        ),
        yield_curve_slope=yield_curve,
        inflation_rate=cpi.change_1y if cpi else None,
        m2_growth=m2.change_1y if m2 else None,
        policy_stance=stance,
        last_updated=datetime.utcnow()
    )

def _calculate_yield_curve(self, two_year: float, ten_year: float) -> float:
    """
    计算收益率曲线斜率
    
    收益率曲线 = 10年期 - 2年期
    
    解读:
    - > 1.0: 陡峭，经济扩张预期
    - 0.5-1.0: 正常
    - 0-0.5: 平坦，经济放缓
    - < 0: 倒挂，衰退预警
    """
    return round(ten_year - two_year, 2)

def _analyze_monetary_policy_stance(
    self,
    fed_funds_rate: float,
    inflation_rate: float,
    m2_growth: float
) -> str:
    """
    分析货币政策立场
    
    判断逻辑:
    1. 利率 < 2% 且 M2增速 > 10% → 宽松
    2. 利率 > 4% 且 通胀 > 5% → 紧缩
    3. 其他 → 中性
    """
    if fed_funds_rate < 2.0 and m2_growth > 10:
        return "宽松 (Accommodative)"
    elif fed_funds_rate > 4.0 and inflation_rate > 5:
        return "紧缩 (Restrictive)"
    elif fed_funds_rate > 3.0 and inflation_rate > 3:
        return "偏紧 (Slightly Restrictive)"
    elif fed_funds_rate < 3.0:
        return "偏松 (Slightly Accommodative)"
    else:
        return "中性 (Neutral)"
```

### 4.2 经济周期分析

```python
async def get_economic_cycle(self, use_cache: bool = True) -> EconomicCycleDTO:
    """
    获取经济周期指标
    
    包含:
    - GDP增长率
    - 失业率
    - 制造业PMI
    - 零售销售增长
    - 经济周期阶段判断
    """
    
    # 获取指标
    gdp_growth = await self._get_or_fetch_indicator("gdp_growth")
    unemployment = await self._get_or_fetch_indicator("unemployment")
    pmi = await self._get_or_fetch_indicator("manufacturing_pmi")
    retail_sales = await self._get_or_fetch_indicator("retail_sales")
    
    # 判断周期阶段
    cycle_phase = self._determine_economic_cycle_phase(
        gdp_growth.value if gdp_growth else 0,
        unemployment.value if unemployment else 0,
        pmi.value if pmi else 50
    )
    
    return EconomicCycleDTO(
        gdp_growth_rate=gdp_growth.value if gdp_growth else None,
        unemployment_rate=unemployment.value if unemployment else None,
        pmi=pmi.value if pmi else None,
        retail_sales_growth=retail_sales.change_1y if retail_sales else None,
        cycle_phase=cycle_phase,
        last_updated=datetime.utcnow()
    )

def _determine_economic_cycle_phase(
    self,
    gdp_growth: float,
    unemployment: float,
    pmi: float
) -> str:
    """
    判断经济周期阶段
    
    四阶段模型:
    1. 扩张期 (Expansion): GDP增长加速, 失业率下降, PMI > 50
    2. 繁荣期 (Peak): GDP高增长, 失业率极低, PMI > 55
    3. 衰退期 (Contraction): GDP放缓, 失业率上升, PMI < 50
    4. 复苏期 (Trough/Recovery): GDP开始回升, 失业率见顶, PMI回到50附近
    """
    
    if gdp_growth > 3.0 and unemployment < 4.0 and pmi > 55:
        return "繁荣期 (Peak)"
    elif gdp_growth > 2.0 and pmi > 50:
        return "扩张期 (Expansion)"
    elif gdp_growth < 1.0 and pmi < 50:
        return "衰退期 (Contraction)"
    elif gdp_growth < 2.0 and pmi >= 50:
        return "复苏期 (Recovery)"
    else:
        return "过渡期 (Transition)"
```

### 4.3 市场情绪分析

```python
async def get_market_sentiment(self, use_cache: bool = True) -> MarketSentimentDTO:
    """
    获取市场情绪指标
    
    包含:
    - VIX恐慌指数
    - Put/Call比率
    - 消费者信心指数
    - 市场情绪判断
    """
    
    # 获取指标
    vix = await self._fetch_vix()
    put_call_ratio = await self._calculate_put_call_ratio()
    consumer_sentiment = await self._get_or_fetch_indicator("consumer_sentiment")
    
    # 判断市场情绪
    sentiment = self._analyze_market_sentiment(
        vix,
        put_call_ratio,
        consumer_sentiment.value if consumer_sentiment else 0
    )
    
    return MarketSentimentDTO(
        vix_index=vix,
        put_call_ratio=put_call_ratio,
        consumer_confidence=consumer_sentiment.value if consumer_sentiment else None,
        sentiment_score=sentiment["score"],
        sentiment_label=sentiment["label"],
        last_updated=datetime.utcnow()
    )

def _analyze_market_sentiment(
    self,
    vix: float,
    put_call_ratio: float,
    consumer_confidence: float
) -> dict:
    """
    综合分析市场情绪
    
    评分规则 (0-100):
    - VIX: < 15 → 乐观(+30), 15-25 → 中性(0), > 25 → 恐慌(-30)
    - Put/Call: < 0.8 → 看涨(+20), 0.8-1.2 → 中性(0), > 1.2 → 看跌(-20)
    - 消费者信心: > 90 → 高(+20), 70-90 → 中(0), < 70 → 低(-20)
    
    基准分: 50
    """
    base_score = 50
    adjustments = 0
    
    # VIX调整
    if vix < 15:
        adjustments += 30
    elif vix > 25:
        adjustments -= 30
    elif vix > 20:
        adjustments -= 15
    
    # Put/Call调整
    if put_call_ratio < 0.8:
        adjustments += 20
    elif put_call_ratio > 1.2:
        adjustments -= 20
    
    # 消费者信心调整
    if consumer_confidence > 90:
        adjustments += 20
    elif consumer_confidence < 70:
        adjustments -= 20
    
    final_score = max(0, min(100, base_score + adjustments))
    
    # 情绪标签
    if final_score >= 70:
        label = "乐观 (Bullish)"
    elif final_score >= 55:
        label = "偏乐观 (Slightly Bullish)"
    elif final_score >= 45:
        label = "中性 (Neutral)"
    elif final_score >= 30:
        label = "偏悲观 (Slightly Bearish)"
    else:
        label = "悲观 (Bearish)"
    
    return {
        "score": final_score,
        "label": label
    }
```

---

## 5. 缓存和刷新策略

### 5.1 缓存读取

```python
async def _get_or_fetch_indicator(
    self,
    indicator_name: str
) -> Optional[MacroIndicator]:
    """
    获取指标（优先缓存）
    
    逻辑:
    1. 查询缓存
    2. 检查是否过期（6小时）
    3. 过期则重新获取
    """
    # 查询缓存
    cached = await self._get_cached_indicator(indicator_name)
    
    # 检查是否有效
    if cached and (datetime.utcnow() - cached.timestamp) < self.cache_duration:
        return cached
    
    # 重新获取
    series_id = self.FRED_SERIES.get(indicator_name)
    if not series_id:
        return None
    
    indicator = await self._fetch_fred_indicator(indicator_name, series_id)
    
    if indicator:
        await self._save_indicator(indicator)
    
    return indicator

async def _get_cached_indicator(
    self,
    indicator_name: str
) -> Optional[MacroIndicator]:
    """查询数据库缓存"""
    stmt = select(MacroIndicator).where(
        MacroIndicator.indicator_name == indicator_name
    ).order_by(MacroIndicator.timestamp.desc()).limit(1)
    
    result = await self.session.execute(stmt)
    return result.scalar_one_or_none()
```

### 5.2 批量刷新（定时任务）

```python
async def refresh_all_indicators(self) -> Dict[str, int]:
    """
    刷新所有宏观指标
    
    由定时任务调用（每天早上9点）
    
    返回:
        {"success": 成功数量, "failed": 失败数量}
    """
    success_count = 0
    failed_count = 0
    
    for indicator_name, series_id in self.FRED_SERIES.items():
        try:
            indicator = await self._fetch_fred_indicator(indicator_name, series_id)
            if indicator:
                await self._save_indicator(indicator)
                success_count += 1
            else:
                failed_count += 1
        except Exception as e:
            logger.error(f"Failed to refresh {indicator_name}: {e}")
            failed_count += 1
    
    # 刷新市场情绪指标
    try:
        vix = await self._fetch_vix()
        if vix:
            vix_indicator = MacroIndicator(
                indicator_name="vix",
                indicator_category="market_sentiment",
                value=vix,
                unit="Index",
                data_source="Yahoo Finance",
                timestamp=datetime.utcnow()
            )
            await self._save_indicator(vix_indicator)
            success_count += 1
    except:
        failed_count += 1
    
    await self.session.commit()
    
    return {
        "success": success_count,
        "failed": failed_count,
        "total": success_count + failed_count
    }
```

---

## 6. 错误处理

### 6.1 API限流处理

```python
class FREDRateLimitError(Exception):
    """FRED API限流异常"""
    pass

async def _fetch_fred_indicator_with_retry(
    self,
    indicator_name: str,
    series_id: str,
    max_retries: int = 3
) -> Optional[MacroIndicator]:
    """
    带重试的FRED数据获取
    
    处理:
    - API限流: 等待后重试
    - 网络错误: 指数退避
    - 数据不存在: 返回None
    """
    import asyncio
    
    for attempt in range(max_retries):
        try:
            return await self._fetch_fred_indicator(indicator_name, series_id)
        except FREDRateLimitError:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避
                logger.warning(f"FRED rate limit hit, waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                raise
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                return None
    
    return None
```

---

## 7. 数据库交互

```python
async def _save_indicator(self, indicator: MacroIndicator) -> None:
    """保存指标到数据库"""
    self.session.add(indicator)
    # 注意: commit由调用方统一处理（批量操作优化）

async def get_indicator_history(
    self,
    indicator_name: str,
    days: int = 30
) -> List[MacroIndicator]:
    """
    获取指标历史数据
    
    用于绘制趋势图
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    stmt = select(MacroIndicator).where(
        and_(
            MacroIndicator.indicator_name == indicator_name,
            MacroIndicator.timestamp >= cutoff_date
        )
    ).order_by(MacroIndicator.timestamp.asc())
    
    result = await self.session.execute(stmt)
    return result.scalars().all()
```

---

## 8. 实现检查清单

- [ ] 创建 `app/services/macro_indicators_service.py`
- [ ] 集成FRED API客户端
- [ ] 实现15个核心宏观指标获取
- [ ] 实现货币政策分析逻辑
- [ ] 实现经济周期判断逻辑
- [ ] 实现市场情绪分析逻辑
- [ ] 实现缓存机制
- [ ] 实现批量刷新功能
- [ ] 添加错误处理和重试
- [ ] 配置FRED API Key
- [ ] 编写单元测试
- [ ] 性能测试（批量刷新 < 30s）

---

**预计工作量**: 8-10小时
**优先级**: P0 (核心功能)
**外部依赖**: FRED API Key (需注册)
**月度成本**: $0 (FRED API免费)
