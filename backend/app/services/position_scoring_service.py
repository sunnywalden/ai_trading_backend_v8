"""
持仓评分服务

根据 MODULE_2 设计实现：
- 整合技术面（40%）+ 基本面（40%）+ 情绪面（20%）
- 生成综合评分和投资建议
- 计算目标仓位、止损止盈位
- 风险等级评估
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position_score import PositionScore
from app.services.technical_analysis_service import TechnicalAnalysisService
from app.services.fundamental_analysis_service import FundamentalAnalysisService


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "LOW"          # 低风险 (80-100分)
    MEDIUM = "MEDIUM"    # 中风险 (60-79分)
    HIGH = "HIGH"        # 高风险 (40-59分)
    EXTREME = "EXTREME"  # 极高风险 (0-39分)


class Recommendation(str, Enum):
    """投资建议"""
    STRONG_BUY = "STRONG_BUY"  # 强力买入 (90-100分)
    BUY = "BUY"                 # 买入 (75-89分)
    HOLD = "HOLD"               # 持有 (55-74分)
    REDUCE = "REDUCE"           # 减仓 (40-54分)
    SELL = "SELL"               # 卖出 (0-39分)


class PositionScoringService:
    """持仓评分服务"""

    def __init__(self):
        # 权重配置
        self.weight_technical = 0.40    # 技术面权重 40%
        self.weight_fundamental = 0.40  # 基本面权重 40%
        self.weight_sentiment = 0.20    # 情绪面权重 20%

    def _get_session(self):
        """延迟导入session避免循环依赖"""
        from app.models.db import SessionLocal
        return SessionLocal()

    async def calculate_position_score(
        self, 
        symbol: str,
        current_price: Optional[float] = None,
        force_refresh: bool = False,
        technical_data=None,
        fundamental_data=None
    ) -> Optional[PositionScore]:
        """
        计算持仓综合评分（改进：接受预计算的技术/基本面数据与可选 current_price）
        
        Args:
            symbol: 股票代码
            current_price: 当前价格（若未提供，将主动拉取）
            force_refresh: 是否强制刷新
            technical_data: 可选的预计算技术面数据（避免重复请求）
            fundamental_data: 可选的预计算基本面数据（避免重复请求）
        
        Returns:
            持仓评分对象，失败返回None
        """
        try:
            # 准备服务
            fundamental_service = FundamentalAnalysisService()

            # 获取或确认当前价格
            if current_price is None:
                from app.providers.market_data_provider import MarketDataProvider
                market_provider = MarketDataProvider()
                try:
                    current_price = await market_provider.get_current_price(symbol)
                except Exception:
                    current_price = 0.0

            # 获取技术面数据（如果未提供）
            technical_score = 50.0
            technical_obj = technical_data
            try:
                if technical_obj is None:
                    async with self._get_session() as session:
                        technical_service = TechnicalAnalysisService(session)
                        technical_obj = await technical_service.get_technical_analysis(
                            symbol,
                            timeframe="1D",
                            use_cache=not force_refresh,
                            account_id="DEMO",
                            use_ai=False
                        )
                if technical_obj:
                    technical_score = self._calculate_technical_score_from_dto(technical_obj)
            except Exception as e:
                print(f"Technical analysis failed for {symbol}: {e}, using default score")

            # 获取基本面数据（如果未提供）
            fundamental_score = 50.0
            fundamental_obj = fundamental_data
            try:
                if fundamental_obj is None:
                    fundamental_obj = await fundamental_service.get_fundamental_data(symbol, force_refresh)
                if fundamental_obj and hasattr(fundamental_obj, 'overall_score'):
                    fundamental_score = fundamental_obj.overall_score
            except Exception as e:
                print(f"Fundamental analysis failed for {symbol}: {e}, using default score")

            # 计算情绪面评分
            sentiment_score = self._calculate_sentiment_score(technical_obj) if technical_obj else 50.0

            # 综合评分
            overall_score = (
                technical_score * self.weight_technical +
                fundamental_score * self.weight_fundamental +
                sentiment_score * self.weight_sentiment
            )

            # 风险等级与建议
            risk_level = self._determine_risk_level(overall_score)
            recommendation = self._generate_recommendation(
                overall_score,
                technical_score,
                fundamental_score
            )

            # 计算目标仓位与止损止盈
            target_position = self._calculate_target_position(overall_score, risk_level)
            stop_loss, take_profit = self._calculate_stop_loss_take_profit(
                current_price,
                technical_obj,
                risk_level
            )

            # 保存到数据库（使用新的session）
            async with self._get_session() as session:
                position_score = PositionScore(
                    account_id="DEMO",
                    symbol=symbol,
                    sector=getattr(fundamental_obj, 'sector', None),
                    industry=getattr(fundamental_obj, 'industry', None),
                    overall_score=int(overall_score),
                    technical_score=int(technical_score),
                    fundamental_score=int(fundamental_score),
                    sentiment_score=int(sentiment_score),
                    pe_ratio=getattr(fundamental_obj, 'pe_ratio', None),
                    peg_ratio=getattr(fundamental_obj, 'peg_ratio', None),
                    beta=getattr(fundamental_obj, 'beta', None),
                    roe=getattr(fundamental_obj, 'roe', None),
                    revenue_growth_yoy=getattr(fundamental_obj, 'revenue_growth_yoy', None),
                    recommendation=recommendation.value,
                    timestamp=datetime.now()
                )

                session.add(position_score)
                await session.commit()
                await session.refresh(position_score)

                position_score.risk_level = risk_level.value
                position_score.target_position = target_position
                position_score.stop_loss = stop_loss
                position_score.take_profit = take_profit

                return position_score
        except Exception as e:
            print(f"Error calculating position score for {symbol}: {e}")
            return None
    
    def _calculate_technical_score_from_dto(self, technical_data) -> float:
        """从TechnicalAnalysisDTO计算技术评分"""
        if not technical_data:
            return 50.0
        
        scores = []
        
        # 趋势评分
        if hasattr(technical_data, 'trend_strength'):
            scores.append(technical_data.trend_strength)
        
        # RSI评分 (转换为0-100)
        if hasattr(technical_data, 'rsi') and technical_data.rsi:
            rsi_val = technical_data.rsi.value if hasattr(technical_data.rsi, 'value') else technical_data.rsi
            if 30 <= rsi_val <= 70:
                rsi_score = 80  # 健康区间
            elif rsi_val < 30:
                rsi_score = 90  # 超卖机会
            else:
                rsi_score = 40  # 超买风险
            scores.append(rsi_score)
        
        return sum(scores) / len(scores) if scores else 50.0

    def _calculate_sentiment_score(self, technical_data) -> float:
        """
        计算市场情绪评分 (0-100)
        
        基于技术指标判断市场情绪：
        - RSI: 反映超买超卖
        - MACD: 反映趋势强度
        - 成交量: 反映市场参与度
        """
        if not technical_data:
            return 50.0
        
        scores = []
        
        # RSI情绪 (30-70为中性)
        rsi = None
        if hasattr(technical_data, 'rsi') and technical_data.rsi is not None:
            # TechnicalAnalysisDTO.rsi 是一个对象（含 value/status/signal），不是数值
            rsi = technical_data.rsi.value if hasattr(technical_data.rsi, 'value') else technical_data.rsi

        if rsi is not None:
            if 40 <= rsi <= 60:
                rsi_sentiment = 70  # 中性偏好
            elif 30 <= rsi < 40:
                rsi_sentiment = 80  # 超卖，潜在买入机会
            elif 60 < rsi <= 70:
                rsi_sentiment = 60  # 偏强，谨慎
            elif rsi < 30:
                rsi_sentiment = 90  # 严重超卖
            else:  # rsi > 70
                rsi_sentiment = 40  # 超买，风险较高
            scores.append(rsi_sentiment)
        
        # MACD情绪 (正值看涨，负值看跌)
        macd_value = None
        macd_signal_line = None
        if hasattr(technical_data, 'macd') and technical_data.macd is not None:
            # TechnicalAnalysisDTO.macd 是对象（含 value/signal_line/histogram/status）
            macd_value = technical_data.macd.value if hasattr(technical_data.macd, 'value') else technical_data.macd
            macd_signal_line = (
                technical_data.macd.signal_line
                if hasattr(technical_data.macd, 'signal_line')
                else None
            )

        if macd_value is not None and macd_signal_line is not None:
            macd_diff = macd_value - macd_signal_line
            if macd_diff > 0:
                macd_sentiment = min(70 + abs(macd_diff) * 100, 90)  # 看涨情绪
            else:
                macd_sentiment = max(30 - abs(macd_diff) * 100, 10)  # 看跌情绪
            scores.append(macd_sentiment)
        
        # 成交量情绪（相对于平均成交量）
        if technical_data.volume_ratio is not None:
            vol_ratio = technical_data.volume_ratio
            if vol_ratio > 1.5:
                vol_sentiment = 80  # 高成交量，活跃
            elif vol_ratio > 1.0:
                vol_sentiment = 70  # 正常偏高
            elif vol_ratio > 0.7:
                vol_sentiment = 60  # 正常
            else:
                vol_sentiment = 50  # 低迷
            scores.append(vol_sentiment)
        
        return sum(scores) / len(scores) if scores else 50.0

    def _determine_risk_level(self, overall_score: float) -> RiskLevel:
        """根据综合评分确定风险等级"""
        if overall_score >= 80:
            return RiskLevel.LOW
        elif overall_score >= 60:
            return RiskLevel.MEDIUM
        elif overall_score >= 40:
            return RiskLevel.HIGH
        else:
            return RiskLevel.EXTREME

    def _generate_recommendation(
        self, 
        overall_score: float,
        technical_score: float,
        fundamental_score: float
    ) -> Recommendation:
        """
        生成投资建议
        
        规则：
        - 综合评分 >= 90: 强力买入
        - 综合评分 75-89: 买入
        - 综合评分 55-74: 持有
        - 综合评分 40-54: 减仓
        - 综合评分 < 40: 卖出
        
        特殊情况：
        - 技术面和基本面差异超过30分：降级建议
        """
        # 检查技术面和基本面是否背离
        divergence = abs(technical_score - fundamental_score)
        
        if overall_score >= 90 and divergence < 30:
            return Recommendation.STRONG_BUY
        elif overall_score >= 75 and divergence < 30:
            return Recommendation.BUY
        elif overall_score >= 55:
            return Recommendation.HOLD
        elif overall_score >= 40:
            return Recommendation.REDUCE
        else:
            return Recommendation.SELL

    def _calculate_target_position(
        self, 
        overall_score: float, 
        risk_level: RiskLevel
    ) -> float:
        """
        计算建议持仓比例 (0-1)
        
        规则：
        - 低风险(80-100分): 60-100% 仓位
        - 中风险(60-79分): 30-60% 仓位
        - 高风险(40-59分): 10-30% 仓位
        - 极高风险(0-39分): 0-10% 仓位
        """
        if risk_level == RiskLevel.LOW:
            # 80-100分 -> 60-100%
            return 0.6 + (overall_score - 80) / 20 * 0.4
        elif risk_level == RiskLevel.MEDIUM:
            # 60-79分 -> 30-60%
            return 0.3 + (overall_score - 60) / 20 * 0.3
        elif risk_level == RiskLevel.HIGH:
            # 40-59分 -> 10-30%
            return 0.1 + (overall_score - 40) / 20 * 0.2
        else:  # EXTREME
            # 0-39分 -> 0-10%
            return min(overall_score / 40 * 0.1, 0.1)

    def _calculate_stop_loss_take_profit(
        self,
        current_price: float,
        technical_data,
        risk_level: RiskLevel
    ) -> tuple[Optional[float], Optional[float]]:
        """
        计算止损和止盈位
        
        止损规则：
        - 低风险: -8%
        - 中风险: -10%
        - 高风险: -12%
        - 极高风险: -15%
        
        止盈规则：
        - 基于支撑阻力位，如果有的话
        - 否则使用固定比例: 15-25%
        """
        # 计算止损位
        if risk_level == RiskLevel.LOW:
            stop_loss_pct = 0.08
        elif risk_level == RiskLevel.MEDIUM:
            stop_loss_pct = 0.10
        elif risk_level == RiskLevel.HIGH:
            stop_loss_pct = 0.12
        else:  # EXTREME
            stop_loss_pct = 0.15
        
        stop_loss = current_price * (1 - stop_loss_pct)
        
        # 计算止盈位
        # 优先使用阻力位（TechnicalAnalysisDTO 里通常是 resistance_levels: List[float]）
        take_profit = None
        resistance_levels = None
        if technical_data is not None:
            if hasattr(technical_data, 'resistance_levels'):
                resistance_levels = getattr(technical_data, 'resistance_levels')
            elif hasattr(technical_data, 'resistance'):
                resistance_levels = getattr(technical_data, 'resistance')

        if isinstance(resistance_levels, list) and resistance_levels:
            take_profit = float(resistance_levels[0])
        else:
            # 使用固定比例
            if risk_level == RiskLevel.LOW:
                take_profit_pct = 0.25  # 25%
            elif risk_level == RiskLevel.MEDIUM:
                take_profit_pct = 0.20  # 20%
            else:
                take_profit_pct = 0.15  # 15%
            
            take_profit = current_price * (1 + take_profit_pct)
        
        return round(stop_loss, 2), round(float(take_profit), 2)

    async def get_all_position_scores(
        self, 
        symbols: List[str], 
        force_refresh: bool = False
    ) -> Dict[str, PositionScore]:
        """
        批量获取持仓评分
        
        Args:
            symbols: 股票代码列表
            force_refresh: 是否强制刷新
            
        Returns:
            {symbol: PositionScore} 字典
        """
        results = {}
        
        for symbol in symbols:
            try:
                # 先尝试从缓存获取
                if not force_refresh:
                    cached = await self._get_cached_score(symbol)
                    if cached:
                        results[symbol] = cached
                        continue
                
                # 计算评分
                score = await self.calculate_position_score(
                    symbol,
                    force_refresh=force_refresh
                )
                if score:
                    results[symbol] = score
                        
            except Exception as e:
                print(f"Error calculating score for {symbol}: {e}")
        
        return results

    async def _get_cached_score(self, symbol: str) -> Optional[PositionScore]:
        """获取缓存的评分（1小时内）"""
        cutoff_time = datetime.now() - timedelta(hours=1)
        
        async with self._get_session() as session:
            stmt = select(PositionScore).where(
                PositionScore.symbol == symbol,
                PositionScore.timestamp >= cutoff_time
            ).order_by(PositionScore.timestamp.desc())
            
            result = await session.execute(stmt)
            # 使用 scalars().first() 而不是 scalar_one_or_none() 以处理可能的重复记录
            cached_score = result.scalars().first()
            
            if cached_score:
                # 为缓存的对象添加动态计算的属性
                overall = cached_score.overall_score or 50
                cached_score.risk_level = self._determine_risk_level(overall).value
                cached_score.target_position = self._calculate_target_position(
                    overall, 
                    self._determine_risk_level(overall)
                )
                # 使用默认止损止盈（因为缓存中没有价格信息）
                cached_score.stop_loss = 0.0
                cached_score.take_profit = 0.0
            
            return cached_score

    async def get_high_risk_positions(self) -> List[PositionScore]:
        """
        获取所有高风险和极高风险的持仓
        
        用于风险预警
        """
        async with self._get_session() as session:
            stmt = select(PositionScore).where(
                PositionScore.risk_level.in_([
                    RiskLevel.HIGH.value, 
                    RiskLevel.EXTREME.value
                ]),
                PositionScore.timestamp >= datetime.now() - timedelta(hours=24)
            ).order_by(PositionScore.overall_score.asc())
            
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_buy_candidates(self, min_score: float = 75.0) -> List[PositionScore]:
        """
        获取买入候选（评分 >= min_score）
        
        用于寻找投资机会
        """
        async with self._get_session() as session:
            stmt = select(PositionScore).where(
                PositionScore.overall_score >= min_score,
                PositionScore.recommendation.in_([
                    Recommendation.BUY.value,
                    Recommendation.STRONG_BUY.value
                ]),
                PositionScore.timestamp >= datetime.now() - timedelta(hours=24)
            ).order_by(PositionScore.overall_score.desc())
            
            result = await session.execute(stmt)
            return list(result.scalars().all())
