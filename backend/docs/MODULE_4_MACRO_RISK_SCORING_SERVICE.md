# 模块4: 宏观风险评分服务设计

## 1. 服务概述

### 职责
- 整合5个维度的宏观风险评分
- 货币政策风险评估
- 地缘政治风险评估
- 行业泡沫风险评估
- 经济周期风险评估
- 市场情绪风险评估
- 生成综合风险等级和预警

### 依赖
- `app.services.macro_indicators_service.MacroIndicatorsService`
- `app.services.geopolitical_events_service.GeopoliticalEventsService`
- `app.models.macro_risk.MacroRiskScore`

---

## 2. 类设计

### 2.1 服务类结构

```python
# app/services/macro_risk_scoring_service.py

from typing import Optional, List, Dict
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from enum import Enum

from app.models.macro_risk import MacroRiskScore
from app.services.macro_indicators_service import MacroIndicatorsService
from app.services.geopolitical_events_service import GeopoliticalEventsService
from app.schemas.macro_risk import (
    MacroRiskOverviewResponse,
    OverallRiskDTO,
    RiskBreakdownDTO,
    MonetaryPolicyDTO,
    GeopoliticalDTO,
    SectorBubbleDTO,
    EconomicCycleDTO,
    MarketSentimentDTO
)

class RiskLevel(str, Enum):
    LOW = "LOW"           # 低风险 (80-100分)
    MEDIUM = "MEDIUM"     # 中等风险 (60-79分)
    HIGH = "HIGH"         # 高风险 (40-59分)
    EXTREME = "EXTREME"   # 极端风险 (0-39分)

class MacroRiskScoringService:
    """宏观风险评分服务"""
    
    # 5个维度的权重配置
    WEIGHT_MONETARY_POLICY = 0.30   # 货币政策 30%
    WEIGHT_GEOPOLITICAL = 0.20      # 地缘政治 20%
    WEIGHT_SECTOR_BUBBLE = 0.20     # 行业泡沫 20%
    WEIGHT_ECONOMIC_CYCLE = 0.20    # 经济周期 20%
    WEIGHT_MARKET_SENTIMENT = 0.10  # 市场情绪 10%
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.macro_indicators = MacroIndicatorsService(session)
        self.geopolitical = GeopoliticalEventsService(session)
        self.cache_duration = timedelta(hours=6)
    
    async def get_macro_risk_overview(
        self,
        use_cache: bool = True
    ) -> MacroRiskOverviewResponse:
        """获取宏观风险总览（主入口）"""
        pass
    
    async def _calculate_all_risk_scores(self) -> Dict[str, float]:
        """计算所有维度风险评分"""
        pass
    
    async def _calculate_monetary_policy_risk(self) -> float:
        """计算货币政策风险评分 (0-100)"""
        pass
    
    async def _calculate_geopolitical_risk(self) -> float:
        """计算地缘政治风险评分 (0-100)"""
        pass
    
    async def _calculate_sector_bubble_risk(self) -> float:
        """计算行业泡沫风险评分 (0-100)"""
        pass
    
    async def _calculate_economic_cycle_risk(self) -> float:
        """计算经济周期风险评分 (0-100)"""
        pass
    
    async def _calculate_market_sentiment_risk(self) -> float:
        """计算市场情绪风险评分 (0-100)"""
        pass
    
    def _calculate_overall_risk_score(
        self,
        monetary: float,
        geopolitical: float,
        sector_bubble: float,
        economic_cycle: float,
        market_sentiment: float
    ) -> float:
        """计算综合风险评分（加权平均）"""
        pass
    
    def _determine_risk_level(self, score: float) -> RiskLevel:
        """判定风险等级"""
        pass
    
    async def _save_risk_score(self, score: MacroRiskScore) -> None:
        """保存风险评分到数据库"""
        pass
    
    async def _get_cached_risk_score(self) -> Optional[MacroRiskScore]:
        """获取缓存的风险评分"""
        pass
    
    def _generate_risk_alerts(
        self,
        overall_score: float,
        dimension_scores: Dict[str, float]
    ) -> List[str]:
        """生成风险预警"""
        pass
```

---

## 3. 五维度风险评分算法

### 3.1 货币政策风险 (30%)

```python
async def _calculate_monetary_policy_risk(self) -> float:
    """
    货币政策风险评分 (0-100，分数越高风险越低)
    
    考虑因素:
    1. 利率水平 (40%):
       - 极低利率(<1%): 50分 (政策空间受限)
       - 正常利率(2-4%): 80分 (健康)
       - 高利率(>5%): 40分 (紧缩压力)
    
    2. 收益率曲线 (30%):
       - 陡峭(>1.5%): 80分 (经济扩张)
       - 正常(0.5-1.5%): 70分
       - 平坦(0-0.5%): 50分 (增长放缓)
       - 倒挂(<0): 20分 (衰退预警)
    
    3. 通胀压力 (30%):
       - 温和通胀(2-3%): 80分 (理想)
       - 低通胀(<2%): 60分 (需刺激)
       - 高通胀(>4%): 30分 (需紧缩)
       - 恶性通胀(>7%): 10分 (严重)
    """
    
    # 获取货币政策指标
    monetary_policy = await self.macro_indicators.get_monetary_policy()
    
    scores = []
    weights = []
    
    # 1. 利率水平评分
    fed_rate = monetary_policy.fed_funds_rate.value
    if fed_rate < 1.0:
        rate_score = 50
    elif 2.0 <= fed_rate <= 4.0:
        rate_score = 80
    elif fed_rate > 5.0:
        rate_score = 40
    else:
        rate_score = 70
    scores.append(rate_score)
    weights.append(0.4)
    
    # 2. 收益率曲线评分
    yield_curve = monetary_policy.yield_curve_slope
    if yield_curve > 1.5:
        curve_score = 80
    elif 0.5 <= yield_curve <= 1.5:
        curve_score = 70
    elif 0 <= yield_curve < 0.5:
        curve_score = 50
    else:  # 倒挂
        curve_score = 20
    scores.append(curve_score)
    weights.append(0.3)
    
    # 3. 通胀评分
    inflation = monetary_policy.inflation_rate
    if 2.0 <= inflation <= 3.0:
        inflation_score = 80
    elif inflation < 2.0:
        inflation_score = 60
    elif 3.0 < inflation <= 4.0:
        inflation_score = 50
    elif 4.0 < inflation <= 7.0:
        inflation_score = 30
    else:
        inflation_score = 10
    scores.append(inflation_score)
    weights.append(0.3)
    
    # 加权平均
    total_weight = sum(weights)
    weighted_sum = sum(s * w for s, w in zip(scores, weights))
    return round(weighted_sum / total_weight, 2)
```

### 3.2 地缘政治风险 (20%)

```python
async def _calculate_geopolitical_risk(self) -> float:
    """
    地缘政治风险评分 (0-100，分数越高风险越低)
    
    考虑因素:
    1. 活跃事件数量:
       - 0-1个: 90分 (稳定)
       - 2-3个: 70分 (轻度紧张)
       - 4-5个: 50分 (中度紧张)
       - >5个: 30分 (高度紧张)
    
    2. 事件严重程度:
       - 平均严重度<3: 80分
       - 平均严重度3-5: 60分
       - 平均严重度>5: 30分
    
    3. 市场影响评分:
       - 平均市场影响<30: 80分
       - 平均市场影响30-50: 60分
       - 平均市场影响>50: 40分
    """
    
    # 获取最近30天的地缘政治事件
    events = await self.geopolitical.get_recent_events(days=30)
    
    if not events:
        return 90.0  # 无事件，低风险
    
    # 1. 事件数量评分
    event_count = len(events)
    if event_count <= 1:
        count_score = 90
    elif event_count <= 3:
        count_score = 70
    elif event_count <= 5:
        count_score = 50
    else:
        count_score = 30
    
    # 2. 严重程度评分
    avg_severity = sum(e.severity for e in events) / len(events)
    if avg_severity < 3:
        severity_score = 80
    elif avg_severity <= 5:
        severity_score = 60
    else:
        severity_score = 30
    
    # 3. 市场影响评分
    avg_impact = sum(e.market_impact_score for e in events) / len(events)
    if avg_impact < 30:
        impact_score = 80
    elif avg_impact <= 50:
        impact_score = 60
    else:
        impact_score = 40
    
    # 综合评分
    final_score = count_score * 0.4 + severity_score * 0.3 + impact_score * 0.3
    return round(final_score, 2)
```

### 3.3 行业泡沫风险 (20%)

```python
async def _calculate_sector_bubble_risk(self) -> float:
    """
    行业泡沫风险评分 (0-100，分数越高风险越低)
    
    考虑因素:
    1. 估值水平 - 纳斯达克PE:
       - PE < 20: 80分 (合理)
       - PE 20-30: 60分 (偏高)
       - PE 30-40: 40分 (高估)
       - PE > 40: 20分 (泡沫)
    
    2. 市场集中度 - 前10大公司市值占比:
       - < 30%: 80分 (分散)
       - 30-40%: 60分 (中等)
       - 40-50%: 40分 (集中)
       - > 50%: 20分 (极度集中)
    
    3. IPO热度 - 近期IPO数量和定价:
       - 低IPO活动: 80分 (理性)
       - 正常IPO活动: 60分
       - 过热IPO活动: 30分 (投机)
    """
    
    # 获取市场数据
    try:
        import yfinance as yf
        
        # 1. 纳斯达克PE估值
        ndx = yf.Ticker("^NDX")
        info = ndx.info
        pe_ratio = info.get("trailingPE", 25)
        
        if pe_ratio < 20:
            valuation_score = 80
        elif pe_ratio < 30:
            valuation_score = 60
        elif pe_ratio < 40:
            valuation_score = 40
        else:
            valuation_score = 20
        
        # 2. 市场集中度（简化：使用波动率代理）
        # TODO: 接入实际市场集中度数据
        concentration_score = 60  # 默认中等
        
        # 3. IPO热度（简化）
        # TODO: 接入IPO数据API
        ipo_score = 60  # 默认正常
        
        # 综合评分
        final_score = (
            valuation_score * 0.5 +
            concentration_score * 0.3 +
            ipo_score * 0.2
        )
        
        return round(final_score, 2)
        
    except Exception as e:
        logger.error(f"Failed to calculate sector bubble risk: {e}")
        return 60.0  # 默认中等风险
```

### 3.4 经济周期风险 (20%)

```python
async def _calculate_economic_cycle_risk(self) -> float:
    """
    经济周期风险评分 (0-100，分数越高风险越低)
    
    考虑因素:
    1. 周期阶段:
       - 复苏期: 85分 (机会)
       - 扩张期: 75分 (健康)
       - 繁荣期: 50分 (见顶风险)
       - 衰退期: 25分 (高风险)
    
    2. GDP增长趋势:
       - 增速加快: +10分
       - 增速稳定: 0分
       - 增速放缓: -15分
    
    3. 失业率趋势:
       - 失业率下降: +10分
       - 失业率稳定: 0分
       - 失业率上升: -15分
    """
    
    # 获取经济周期指标
    economic_cycle = await self.macro_indicators.get_economic_cycle()
    
    # 1. 基础周期评分
    cycle_scores = {
        "复苏期 (Recovery)": 85,
        "扩张期 (Expansion)": 75,
        "繁荣期 (Peak)": 50,
        "衰退期 (Contraction)": 25,
        "过渡期 (Transition)": 60
    }
    base_score = cycle_scores.get(economic_cycle.cycle_phase, 60)
    
    # 2. GDP趋势调整
    gdp_growth = economic_cycle.gdp_growth_rate
    # TODO: 比较当前值与3个月前值
    gdp_adjustment = 0  # 简化版
    
    # 3. 失业率趋势调整
    unemployment = economic_cycle.unemployment_rate
    # TODO: 比较当前值与3个月前值
    unemployment_adjustment = 0  # 简化版
    
    final_score = base_score + gdp_adjustment + unemployment_adjustment
    return round(max(0, min(100, final_score)), 2)
```

### 3.5 市场情绪风险 (10%)

```python
async def _calculate_market_sentiment_risk(self) -> float:
    """
    市场情绪风险评分 (0-100，分数越高风险越低)
    
    直接使用 MacroIndicatorsService 的情绪评分
    
    情绪评分已考虑:
    - VIX恐慌指数
    - Put/Call比率
    - 消费者信心指数
    """
    
    sentiment = await self.macro_indicators.get_market_sentiment()
    return sentiment.sentiment_score
```

---

## 4. 综合风险评分

### 4.1 加权计算

```python
def _calculate_overall_risk_score(
    self,
    monetary: float,
    geopolitical: float,
    sector_bubble: float,
    economic_cycle: float,
    market_sentiment: float
) -> float:
    """
    综合风险评分 = 五维度加权平均
    
    权重:
    - 货币政策: 30%
    - 地缘政治: 20%
    - 行业泡沫: 20%
    - 经济周期: 20%
    - 市场情绪: 10%
    
    评分范围: 0-100 (分数越高风险越低)
    """
    overall = (
        monetary * self.WEIGHT_MONETARY_POLICY +
        geopolitical * self.WEIGHT_GEOPOLITICAL +
        sector_bubble * self.WEIGHT_SECTOR_BUBBLE +
        economic_cycle * self.WEIGHT_ECONOMIC_CYCLE +
        market_sentiment * self.WEIGHT_MARKET_SENTIMENT
    )
    return round(overall, 2)
```

### 4.2 风险等级判定

```python
def _determine_risk_level(self, score: float) -> RiskLevel:
    """
    根据综合评分判定风险等级
    
    分级标准:
    - 80-100: LOW (低风险) - 宏观环境良好
    - 60-79: MEDIUM (中等风险) - 宏观环境稳定
    - 40-59: HIGH (高风险) - 宏观环境恶化
    - 0-39: EXTREME (极端风险) - 宏观环境极差
    """
    if score >= 80:
        return RiskLevel.LOW
    elif score >= 60:
        return RiskLevel.MEDIUM
    elif score >= 40:
        return RiskLevel.HIGH
    else:
        return RiskLevel.EXTREME
```

---

## 5. 风险预警生成

### 5.1 预警规则

```python
def _generate_risk_alerts(
    self,
    overall_score: float,
    dimension_scores: Dict[str, float]
) -> List[str]:
    """
    生成风险预警消息
    
    预警触发条件:
    1. 综合评分 < 50: 整体高风险预警
    2. 任意维度 < 40: 单维度极端风险预警
    3. 评分急剧下降: 趋势恶化预警
    """
    
    alerts = []
    
    # 1. 整体风险预警
    if overall_score < 50:
        alerts.append(f"⚠️ 综合宏观风险评分{overall_score}，处于高风险区间")
    elif overall_score < 40:
        alerts.append(f"🚨 综合宏观风险评分{overall_score}，处于极端风险区间，建议降低仓位")
    
    # 2. 单维度预警
    dimension_names = {
        "monetary_policy": "货币政策",
        "geopolitical": "地缘政治",
        "sector_bubble": "行业泡沫",
        "economic_cycle": "经济周期",
        "market_sentiment": "市场情绪"
    }
    
    for dim_key, dim_score in dimension_scores.items():
        if dim_score < 40:
            dim_name = dimension_names.get(dim_key, dim_key)
            alerts.append(f"🚨 {dim_name}风险评分{dim_score}，存在极端风险")
        elif dim_score < 50:
            dim_name = dimension_names.get(dim_key, dim_key)
            alerts.append(f"⚠️ {dim_name}风险评分{dim_score}，风险偏高")
    
    # 3. 收益率曲线倒挂预警（特殊规则）
    if dimension_scores.get("monetary_policy", 100) < 30:
        alerts.append("🔴 收益率曲线可能倒挂，经济衰退风险上升")
    
    return alerts
```

---

## 6. 主入口实现

### 6.1 获取宏观风险总览

```python
async def get_macro_risk_overview(
    self,
    use_cache: bool = True
) -> MacroRiskOverviewResponse:
    """
    获取宏观风险总览
    
    返回完整的5维度风险分析
    """
    
    # 1. 检查缓存
    if use_cache:
        cached = await self._get_cached_risk_score()
        if cached and (datetime.utcnow() - cached.timestamp) < self.cache_duration:
            return self._build_response_from_cache(cached)
    
    # 2. 计算所有维度评分
    dimension_scores = await self._calculate_all_risk_scores()
    
    # 3. 计算综合评分
    overall_score = self._calculate_overall_risk_score(
        dimension_scores["monetary_policy"],
        dimension_scores["geopolitical"],
        dimension_scores["sector_bubble"],
        dimension_scores["economic_cycle"],
        dimension_scores["market_sentiment"]
    )
    
    # 4. 判定风险等级
    risk_level = self._determine_risk_level(overall_score)
    
    # 5. 生成预警
    alerts = self._generate_risk_alerts(overall_score, dimension_scores)
    
    # 6. 保存到数据库
    risk_score = MacroRiskScore(
        overall_score=overall_score,
        risk_level=risk_level.value,
        monetary_policy_score=dimension_scores["monetary_policy"],
        geopolitical_score=dimension_scores["geopolitical"],
        sector_bubble_score=dimension_scores["sector_bubble"],
        economic_cycle_score=dimension_scores["economic_cycle"],
        market_sentiment_score=dimension_scores["market_sentiment"],
        timestamp=datetime.utcnow()
    )
    await self._save_risk_score(risk_score)
    
    # 7. 构建响应
    return await self._build_response(risk_score, alerts)

async def _calculate_all_risk_scores(self) -> Dict[str, float]:
    """并发计算所有维度评分"""
    import asyncio
    
    tasks = {
        "monetary_policy": self._calculate_monetary_policy_risk(),
        "geopolitical": self._calculate_geopolitical_risk(),
        "sector_bubble": self._calculate_sector_bubble_risk(),
        "economic_cycle": self._calculate_economic_cycle_risk(),
        "market_sentiment": self._calculate_market_sentiment_risk()
    }
    
    results = {}
    for key, task in tasks.items():
        results[key] = await task
    
    return results
```

### 6.2 响应构建

```python
async def _build_response(
    self,
    risk_score: MacroRiskScore,
    alerts: List[str]
) -> MacroRiskOverviewResponse:
    """构建完整响应DTO"""
    
    # 获取详细的维度数据
    monetary_policy = await self.macro_indicators.get_monetary_policy()
    economic_cycle = await self.macro_indicators.get_economic_cycle()
    market_sentiment = await self.macro_indicators.get_market_sentiment()
    geopolitical_events = await self.geopolitical.get_recent_events(days=7)
    
    return MacroRiskOverviewResponse(
        overall_risk=OverallRiskDTO(
            score=risk_score.overall_score,
            level=risk_score.risk_level,
            trend="下降" if risk_score.overall_score < 60 else "稳定",  # TODO: 比较历史
            last_updated=risk_score.timestamp
        ),
        risk_breakdown=RiskBreakdownDTO(
            monetary_policy=risk_score.monetary_policy_score,
            geopolitical=risk_score.geopolitical_score,
            sector_bubble=risk_score.sector_bubble_score,
            economic_cycle=risk_score.economic_cycle_score,
            market_sentiment=risk_score.market_sentiment_score
        ),
        monetary_policy=monetary_policy,
        geopolitical=GeopoliticalDTO(
            active_events_count=len(geopolitical_events),
            high_severity_count=len([e for e in geopolitical_events if e.severity >= 7]),
            average_severity=sum(e.severity for e in geopolitical_events) / len(geopolitical_events) if geopolitical_events else 0,
            risk_score=risk_score.geopolitical_score
        ),
        sector_bubble=SectorBubbleDTO(
            # TODO: 实现详细的行业泡沫数据
            risk_score=risk_score.sector_bubble_score,
            high_risk_sectors=[]
        ),
        economic_cycle=economic_cycle,
        market_sentiment=market_sentiment,
        key_events=[
            KeyEventDTO(
                date=e.event_date,
                category=e.event_category,
                title=e.event_title,
                severity=e.severity,
                market_impact=e.market_impact_score
            )
            for e in geopolitical_events[:5]  # 最近5个事件
        ],
        risk_alerts=alerts
    )
```

---

## 7. 缓存机制

```python
async def _get_cached_risk_score(self) -> Optional[MacroRiskScore]:
    """获取最新的风险评分缓存"""
    stmt = select(MacroRiskScore).order_by(
        MacroRiskScore.timestamp.desc()
    ).limit(1)
    
    result = await self.session.execute(stmt)
    return result.scalar_one_or_none()

async def _save_risk_score(self, score: MacroRiskScore) -> None:
    """保存风险评分"""
    self.session.add(score)
    await self.session.commit()
    await self.session.refresh(score)
```

---

## 8. 实现检查清单

- [ ] 创建 `app/services/macro_risk_scoring_service.py`
- [ ] 实现5个维度的风险评分算法
- [ ] 实现综合评分计算
- [ ] 实现风险等级判定
- [ ] 实现风险预警生成
- [ ] 实现主入口方法
- [ ] 实现响应构建逻辑
- [ ] 实现缓存机制
- [ ] 添加错误处理
- [ ] 编写单元测试
- [ ] 集成测试（完整风险分析 < 3s）

---

**预计工作量**: 10-12小时
**优先级**: P0 (核心功能)
**依赖**: MacroIndicatorsService, GeopoliticalEventsService
