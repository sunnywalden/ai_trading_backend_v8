# 模块2: 持仓评分服务设计

## 1. 服务概述

### 职责
- 整合技术面、基本面、情绪面三维度评分
- 计算持仓综合评分和风险等级
- 生成投资建议（BUY/HOLD/REDUCE/SELL）
- 计算目标仓位和止损止盈位
- 识别风险预警信号

### 依赖
- `app.services.technical_analysis_service.TechnicalAnalysisService`
- `app.services.fundamental_analysis_service.FundamentalAnalysisService`
- `app.models.position_score.PositionScore`
- `app.schemas.position_assessment.PositionScoreDTO`

---

## 2. 类设计

### 2.1 服务类结构

```python
# app/services/position_scoring_service.py

from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from enum import Enum

from app.models.position_score import PositionScore
from app.services.technical_analysis_service import TechnicalAnalysisService
from app.services.fundamental_analysis_service import FundamentalAnalysisService
from app.schemas.position_assessment import (
    PositionScoreDTO,
    PositionRecommendationDTO,
    RiskAlertDTO,
    ActionType,
    RiskLevel
)

class PositionScoringService:
    """持仓评分服务"""
    
    # 评分权重配置
    WEIGHT_TECHNICAL = 0.40      # 技术面权重 40%
    WEIGHT_FUNDAMENTAL = 0.40    # 基本面权重 40%
    WEIGHT_SENTIMENT = 0.20      # 情绪面权重 20%
    
    def __init__(self, session: AsyncSession, account_id: str):
        self.session = session
        self.account_id = account_id
        self.technical_service = TechnicalAnalysisService(session)
        self.fundamental_service = FundamentalAnalysisService(session)
        self.cache_duration = timedelta(hours=1)  # 评分每小时更新
    
    async def calculate_position_score(
        self,
        symbol: str,
        current_price: float,
        position_size: float,
        use_cache: bool = True
    ) -> PositionScoreDTO:
        """计算持仓综合评分（主入口）"""
        pass
    
    async def batch_calculate_scores(
        self,
        positions: List[dict]
    ) -> List[PositionScoreDTO]:
        """批量计算持仓评分"""
        pass
    
    async def _get_cached_score(
        self,
        symbol: str
    ) -> Optional[PositionScore]:
        """从数据库获取缓存评分"""
        pass
    
    async def _calculate_scores(
        self,
        symbol: str,
        current_price: float
    ) -> dict:
        """计算三个维度的评分"""
        pass
    
    def _calculate_overall_score(
        self,
        technical_score: float,
        fundamental_score: float,
        sentiment_score: float
    ) -> float:
        """计算综合评分（加权平均）"""
        pass
    
    def _determine_risk_level(
        self,
        overall_score: float
    ) -> RiskLevel:
        """根据评分判定风险等级"""
        pass
    
    def _generate_recommendation(
        self,
        symbol: str,
        overall_score: float,
        technical_score: float,
        fundamental_score: float,
        current_price: float,
        position_size: float
    ) -> PositionRecommendationDTO:
        """生成投资建议"""
        pass
    
    def _calculate_target_position(
        self,
        overall_score: float,
        current_position: float,
        risk_level: RiskLevel
    ) -> float:
        """计算建议仓位"""
        pass
    
    def _calculate_stop_loss_take_profit(
        self,
        symbol: str,
        current_price: float,
        technical_analysis: dict
    ) -> tuple[float, float]:
        """计算止损止盈位"""
        pass
    
    async def _identify_risk_alerts(
        self,
        symbol: str,
        overall_score: float,
        technical_analysis: dict,
        fundamental_analysis: dict
    ) -> List[RiskAlertDTO]:
        """识别风险预警"""
        pass
    
    async def _save_score(
        self,
        score: PositionScore
    ) -> None:
        """保存评分到数据库"""
        pass
```

---

## 3. 评分算法设计

### 3.1 综合评分计算

```python
def _calculate_overall_score(self, technical_score, fundamental_score, sentiment_score):
    """
    综合评分 = 技术面 × 40% + 基本面 × 40% + 情绪面 × 20%
    
    评分范围: 0-100
    - 80-100: 优秀 (BUY)
    - 60-79: 良好 (HOLD/BUY)
    - 40-59: 中等 (HOLD)
    - 20-39: 较差 (REDUCE)
    - 0-19: 差 (SELL)
    """
    overall = (
        technical_score * self.WEIGHT_TECHNICAL +
        fundamental_score * self.WEIGHT_FUNDAMENTAL +
        sentiment_score * self.WEIGHT_SENTIMENT
    )
    return round(overall, 2)
```

### 3.2 技术面评分获取

```python
async def _get_technical_score(self, symbol: str):
    """
    从TechnicalAnalysisService获取技术面评分
    
    评分来源:
    - RSI状态: 超卖(+20), 正常(0), 超买(-20)
    - MACD信号: 金叉(+15), 中性(0), 死叉(-15)
    - 趋势: 强上升(+30), 上升(+20), 震荡(0), 下降(-20), 强下降(-30)
    - 布林带位置: 下轨附近(+10), 中轨(0), 上轨附近(-10)
    - 成交量: 放量(+10), 正常(0), 缩量(-5)
    
    基准分50分，根据信号调整
    """
    technical = await self.technical_service.get_technical_analysis(symbol)
    
    base_score = 50.0
    adjustments = 0.0
    
    # RSI调整
    if technical.rsi:
        if technical.rsi < 30:
            adjustments += 20  # 超卖，买入机会
        elif technical.rsi > 70:
            adjustments -= 20  # 超买，卖出信号
    
    # MACD调整
    if technical.macd_signal == "金叉":
        adjustments += 15
    elif technical.macd_signal == "死叉":
        adjustments -= 15
    
    # 趋势调整
    trend_scores = {
        "强上升": 30,
        "上升": 20,
        "震荡": 0,
        "下降": -20,
        "强下降": -30
    }
    adjustments += trend_scores.get(technical.trend, 0)
    
    # 布林带调整
    if technical.bb_position == "下轨":
        adjustments += 10
    elif technical.bb_position == "上轨":
        adjustments -= 10
    
    # 成交量调整
    if technical.volume_status == "放量":
        adjustments += 10
    elif technical.volume_status == "缩量":
        adjustments -= 5
    
    final_score = max(0, min(100, base_score + adjustments))
    return final_score
```

### 3.3 基本面评分获取

```python
async def _get_fundamental_score(self, symbol: str):
    """
    从FundamentalAnalysisService获取基本面评分
    
    直接使用 fundamental_analysis.overall_score
    """
    fundamental = await self.fundamental_service.get_fundamental_analysis(symbol)
    return fundamental.overall_score
```

### 3.4 情绪面评分计算

```python
async def _calculate_sentiment_score(self, symbol: str):
    """
    情绪面评分（简化版）
    
    数据来源:
    1. 资金流向 (40%):
       - 从Tiger API获取当日资金净流入
       - 大额净流入: 高分
       - 大额净流出: 低分
    
    2. 期权数据 (30%):
       - Put/Call Ratio
       - < 0.7: 看涨情绪强 (高分)
       - > 1.3: 看跌情绪强 (低分)
    
    3. 分析师评级 (30%):
       - 强烈推荐: 90分
       - 推荐: 70分
       - 中性: 50分
       - 减持: 30分
       - 卖出: 10分
    
    暂时使用简化算法，后续可接入社交媒体数据
    """
    base_score = 50.0
    
    # 1. 获取分析师评级
    try:
        recommendations = await self.market_data.get_analyst_recommendations(symbol)
        if recommendations:
            rating_scores = {
                "strongBuy": 90,
                "buy": 70,
                "hold": 50,
                "sell": 30,
                "strongSell": 10
            }
            rating = recommendations[0].get("rating", "hold")
            analyst_score = rating_scores.get(rating, 50)
        else:
            analyst_score = 50
    except:
        analyst_score = 50
    
    # 2. 获取期权数据（简化）
    try:
        options = await self.market_data.get_options_data(symbol)
        if options and "putCallRatio" in options:
            pc_ratio = options["putCallRatio"]
            if pc_ratio < 0.7:
                options_score = 70  # 看涨
            elif pc_ratio > 1.3:
                options_score = 30  # 看跌
            else:
                options_score = 50  # 中性
        else:
            options_score = 50
    except:
        options_score = 50
    
    # 3. 资金流向（暂时使用成交量作为代理指标）
    money_flow_score = 50  # TODO: 接入实际资金流向数据
    
    # 加权平均
    sentiment_score = (
        analyst_score * 0.4 +
        options_score * 0.3 +
        money_flow_score * 0.3
    )
    
    return round(sentiment_score, 2)
```

---

## 4. 风险等级判定

### 4.1 风险等级分类

```python
class RiskLevel(str, Enum):
    LOW = "LOW"           # 低风险 (80-100分)
    MEDIUM = "MEDIUM"     # 中等风险 (60-79分)
    HIGH = "HIGH"         # 高风险 (40-59分)
    EXTREME = "EXTREME"   # 极端风险 (0-39分)

def _determine_risk_level(self, overall_score: float) -> RiskLevel:
    """根据综合评分判定风险等级"""
    if overall_score >= 80:
        return RiskLevel.LOW
    elif overall_score >= 60:
        return RiskLevel.MEDIUM
    elif overall_score >= 40:
        return RiskLevel.HIGH
    else:
        return RiskLevel.EXTREME
```

---

## 5. 投资建议生成

### 5.1 行动建议算法

```python
class ActionType(str, Enum):
    BUY = "BUY"           # 买入
    HOLD = "HOLD"         # 持有
    REDUCE = "REDUCE"     # 减仓
    SELL = "SELL"         # 卖出

def _generate_recommendation(
    self,
    symbol: str,
    overall_score: float,
    technical_score: float,
    fundamental_score: float,
    current_price: float,
    position_size: float
) -> PositionRecommendationDTO:
    """
    投资建议决策树:
    
    1. 综合评分 >= 75 且 技术面 >= 60 且 基本面 >= 60:
       → BUY (增仓或建仓)
    
    2. 综合评分 >= 60:
       → HOLD (持有观望)
    
    3. 综合评分 40-59:
       → REDUCE (减仓)
    
    4. 综合评分 < 40:
       → SELL (清仓)
    
    特殊情况:
    - 如果技术面 < 30 或 基本面 < 30，即使综合分高也降级为 HOLD
    - 如果持仓盈利 > 50%，建议部分止盈 (REDUCE)
    - 如果持仓亏损 > 20%，检查止损条件
    """
    
    # 基础建议
    if overall_score >= 75 and technical_score >= 60 and fundamental_score >= 60:
        action = ActionType.BUY
        reason = f"{symbol}综合表现优异，建议增加仓位"
    elif overall_score >= 60:
        action = ActionType.HOLD
        reason = f"{symbol}表现稳健，建议持有观望"
    elif overall_score >= 40:
        action = ActionType.REDUCE
        reason = f"{symbol}表现一般，建议适当减仓"
    else:
        action = ActionType.SELL
        reason = f"{symbol}表现较差，建议考虑清仓"
    
    # 风险调整
    if technical_score < 30 or fundamental_score < 30:
        if action == ActionType.BUY:
            action = ActionType.HOLD
            reason += "，但需关注技术面或基本面风险"
    
    # 计算目标仓位
    target_position = self._calculate_target_position(
        overall_score, position_size, self._determine_risk_level(overall_score)
    )
    
    # 计算止损止盈
    stop_loss, take_profit = self._calculate_stop_loss_take_profit(
        symbol, current_price, {}  # 传入技术分析结果
    )
    
    return PositionRecommendationDTO(
        action=action,
        target_position_ratio=target_position,
        stop_loss_price=stop_loss,
        take_profit_price=take_profit,
        reason=reason,
        confidence=self._calculate_confidence(overall_score, technical_score, fundamental_score)
    )
```

### 5.2 目标仓位计算

```python
def _calculate_target_position(
    self,
    overall_score: float,
    current_position: float,
    risk_level: RiskLevel
) -> float:
    """
    根据评分和风险等级计算建议仓位比例
    
    基准仓位分配:
    - 80-100分 (LOW): 目标仓位 15-20%
    - 60-79分 (MEDIUM): 目标仓位 10-15%
    - 40-59分 (HIGH): 目标仓位 5-10%
    - 0-39分 (EXTREME): 目标仓位 0-5%
    
    单个标的最大仓位: 20%
    """
    if overall_score >= 80:
        target = 0.15 + (overall_score - 80) / 100 * 0.05  # 15%-20%
    elif overall_score >= 60:
        target = 0.10 + (overall_score - 60) / 80 * 0.05   # 10%-15%
    elif overall_score >= 40:
        target = 0.05 + (overall_score - 40) / 80 * 0.05   # 5%-10%
    else:
        target = max(0, overall_score / 40 * 0.05)          # 0%-5%
    
    return round(target, 4)
```

### 5.3 止损止盈计算

```python
def _calculate_stop_loss_take_profit(
    self,
    symbol: str,
    current_price: float,
    technical_analysis: dict
) -> tuple[float, float]:
    """
    计算止损止盈位
    
    止损策略:
    1. 技术止损: 近期低点或支撑位下方2%
    2. 固定止损: 当前价格下方8-12%（根据波动率）
    
    止盈策略:
    1. 技术止盈: 近期高点或阻力位
    2. 固定止盈: 当前价格上方15-25%（根据评分）
    """
    
    # 获取ATR（平均真实波动幅度）
    atr = technical_analysis.get("atr", current_price * 0.02)
    
    # 计算止损位
    support_level = technical_analysis.get("support", current_price * 0.92)
    stop_loss_technical = support_level * 0.98
    stop_loss_fixed = current_price * (1 - 0.08 - atr / current_price)
    stop_loss = max(stop_loss_technical, stop_loss_fixed)
    
    # 计算止盈位
    resistance_level = technical_analysis.get("resistance", current_price * 1.15)
    take_profit_technical = resistance_level * 1.02
    take_profit_fixed = current_price * 1.20
    take_profit = min(take_profit_technical, take_profit_fixed)
    
    return round(stop_loss, 2), round(take_profit, 2)
```

---

## 6. 风险预警识别

### 6.1 预警规则

```python
async def _identify_risk_alerts(
    self,
    symbol: str,
    overall_score: float,
    technical_analysis: dict,
    fundamental_analysis: dict
) -> List[RiskAlertDTO]:
    """
    识别风险预警信号
    
    预警类型:
    1. 评分急剧下降 (SCORE_DROP)
    2. 技术破位 (TECHNICAL_BREAKDOWN)
    3. 基本面恶化 (FUNDAMENTAL_DETERIORATION)
    4. 高估值风险 (VALUATION_RISK)
    5. 流动性风险 (LIQUIDITY_RISK)
    6. 止损触发 (STOP_LOSS_TRIGGERED)
    """
    
    alerts = []
    
    # 1. 检查评分变化
    previous_score = await self._get_previous_score(symbol)
    if previous_score and (previous_score.overall_score - overall_score) > 20:
        alerts.append(RiskAlertDTO(
            alert_type="SCORE_DROP",
            severity="HIGH",
            message=f"{symbol}综合评分从{previous_score.overall_score}降至{overall_score}，下跌超过20分",
            timestamp=datetime.utcnow()
        ))
    
    # 2. 技术破位检查
    if technical_analysis.get("trend") == "强下降":
        alerts.append(RiskAlertDTO(
            alert_type="TECHNICAL_BREAKDOWN",
            severity="MEDIUM",
            message=f"{symbol}技术面破位，趋势转为强下降",
            timestamp=datetime.utcnow()
        ))
    
    # 3. 基本面恶化
    if fundamental_analysis.get("overall_score", 50) < 30:
        alerts.append(RiskAlertDTO(
            alert_type="FUNDAMENTAL_DETERIORATION",
            severity="HIGH",
            message=f"{symbol}基本面恶化，评分低于30分",
            timestamp=datetime.utcnow()
        ))
    
    # 4. 估值风险
    if fundamental_analysis.get("valuation", {}).get("pe_ratio", 0) > 50:
        alerts.append(RiskAlertDTO(
            alert_type="VALUATION_RISK",
            severity="MEDIUM",
            message=f"{symbol}估值偏高，PE超过50倍",
            timestamp=datetime.utcnow()
        ))
    
    # 5. 流动性风险（成交量异常低）
    if technical_analysis.get("volume_status") == "极度缩量":
        alerts.append(RiskAlertDTO(
            alert_type="LIQUIDITY_RISK",
            severity="LOW",
            message=f"{symbol}成交量异常低，流动性不足",
            timestamp=datetime.utcnow()
        ))
    
    return alerts
```

---

## 7. 批量处理优化

### 7.1 并发计算

```python
async def batch_calculate_scores(self, positions: List[dict]) -> List[PositionScoreDTO]:
    """
    批量计算持仓评分
    
    优化策略:
    1. 并发查询缓存
    2. 并发获取技术面和基本面数据
    3. 批量保存结果
    """
    import asyncio
    
    # 提取标的列表
    symbols = [p["symbol"] for p in positions]
    
    # 并发查询缓存
    cache_tasks = [self._get_cached_score(s) for s in symbols]
    cached_scores = await asyncio.gather(*cache_tasks)
    
    # 识别需要刷新的标的
    to_calculate = []
    results = {}
    for i, symbol in enumerate(symbols):
        cached = cached_scores[i]
        if cached and (datetime.utcnow() - cached.timestamp) < self.cache_duration:
            results[symbol] = self._build_dto(cached)
        else:
            to_calculate.append(positions[i])
    
    # 并发计算新评分
    if to_calculate:
        calc_tasks = [
            self.calculate_position_score(
                p["symbol"],
                p["current_price"],
                p["position_size"],
                use_cache=False
            )
            for p in to_calculate
        ]
        new_scores = await asyncio.gather(*calc_tasks)
        for score in new_scores:
            results[score.symbol] = score
    
    # 按原始顺序返回
    return [results[s] for s in symbols]
```

---

## 8. 缓存策略

### 8.1 缓存读取

```python
async def _get_cached_score(self, symbol: str) -> Optional[PositionScore]:
    """查询最新的评分缓存"""
    stmt = select(PositionScore).where(
        and_(
            PositionScore.account_id == self.account_id,
            PositionScore.symbol == symbol
        )
    ).order_by(PositionScore.timestamp.desc()).limit(1)
    
    result = await self.session.execute(stmt)
    return result.scalar_one_or_none()
```

### 8.2 缓存保存

```python
async def _save_score(self, score: PositionScore):
    """保存评分到数据库"""
    self.session.add(score)
    await self.session.commit()
    await self.session.refresh(score)
```

---

## 9. 置信度计算

```python
def _calculate_confidence(
    self,
    overall_score: float,
    technical_score: float,
    fundamental_score: float
) -> float:
    """
    计算建议的置信度 (0-1)
    
    置信度因素:
    1. 三个维度评分的一致性（方差小→高置信）
    2. 综合评分远离临界值（离50分越远→高置信）
    3. 数据完整性（指标齐全→高置信）
    """
    
    # 1. 一致性检查（标准差）
    scores = [overall_score, technical_score, fundamental_score]
    avg = sum(scores) / len(scores)
    variance = sum((s - avg) ** 2 for s in scores) / len(scores)
    std_dev = variance ** 0.5
    
    # 标准差越小，一致性越高
    consistency_score = max(0, 1 - std_dev / 50)
    
    # 2. 远离临界值
    distance_from_50 = abs(overall_score - 50)
    distance_score = min(1, distance_from_50 / 30)
    
    # 3. 综合置信度
    confidence = (consistency_score * 0.6 + distance_score * 0.4)
    
    return round(confidence, 2)
```

---

## 10. 实现检查清单

- [ ] 创建 `app/services/position_scoring_service.py`
- [ ] 实现综合评分计算逻辑
- [ ] 实现三维度评分获取和整合
- [ ] 实现投资建议生成算法
- [ ] 实现目标仓位计算
- [ ] 实现止损止盈计算
- [ ] 实现风险预警识别
- [ ] 实现批量处理优化
- [ ] 实现置信度计算
- [ ] 添加缓存机制
- [ ] 编写单元测试
- [ ] 性能测试（批量10个标的 < 2s）

---

**预计工作量**: 10-12小时
**优先级**: P0 (核心功能)
**依赖**: TechnicalAnalysisService, FundamentalAnalysisService
