"""技术分析服务"""
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, date

from app.models.technical_indicator import TechnicalIndicator
from app.providers.market_data_provider import MarketDataProvider
from app.providers.technical_calculator import TechnicalIndicatorCalculator
from app.schemas.position_assessment import TechnicalAnalysisDTO


class TechnicalAnalysisService:
    """技术分析服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.market_provider = MarketDataProvider()
        self.calculator = TechnicalIndicatorCalculator()
    
    async def get_technical_analysis(
        self,
        symbol: str,
        timeframe: str = "1D",
        use_cache: bool = True
    ) -> TechnicalAnalysisDTO:
        """获取技术分析
        
        Args:
            symbol: 股票代码
            timeframe: 时间框架
            use_cache: 是否使用缓存
        """
        # 1. 尝试从缓存获取
        if use_cache:
            cached = await self._get_cached_indicators(symbol, timeframe)
            if cached:
                return await self._build_technical_analysis(symbol, cached)
        
        # 2. 从市场获取最新数据
        df = await self.market_provider.get_historical_data(symbol, period="1y", interval="1d")
        
        if df.empty:
            raise ValueError(f"No data available for {symbol}")
        
        # 3. 计算所有技术指标
        df = self.calculator.calculate_all_indicators(df)
        
        # 4. 保存到缓存
        await self._save_indicators_to_cache(symbol, df, timeframe)
        
        # 5. 构建分析结果
        return await self._build_technical_analysis(symbol, df.iloc[-1].to_dict())
    
    async def _get_cached_indicators(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[Dict]:
        """从缓存获取指标"""
        today = date.today()
        
        stmt = select(TechnicalIndicator).where(
            and_(
                TechnicalIndicator.symbol == symbol,
                TechnicalIndicator.timeframe == timeframe,
                TechnicalIndicator.timestamp >= datetime.combine(today, datetime.min.time())
            )
        ).order_by(TechnicalIndicator.timestamp.desc())
        
        result = await self.session.execute(stmt)
        indicator = result.scalars().first()
        
        if not indicator:
            return None
        
        return {
            'Close': indicator.close_price,
            'Volume': indicator.volume,
            'MA_5': indicator.ma_5,
            'MA_20': indicator.ma_20,
            'MA_50': indicator.ma_50,
            'MA_200': indicator.ma_200,
            'RSI_14': indicator.rsi_14,
            'MACD': indicator.macd,
            'MACD_signal': indicator.macd_signal,
            'MACD_histogram': indicator.macd_histogram,
            'BB_upper': indicator.bb_upper,
            'BB_middle': indicator.bb_middle,
            'BB_lower': indicator.bb_lower,
            'ATR_14': indicator.atr_14,
        }
    
    async def _save_indicators_to_cache(
        self,
        symbol: str,
        df,
        timeframe: str
    ):
        """保存指标到缓存"""
        latest = df.iloc[-1]
        
        indicator = TechnicalIndicator(
            symbol=symbol,
            timeframe=timeframe,
            close_price=float(latest['Close']),
            volume=int(latest['Volume']),
            ma_5=float(latest.get('MA_5', 0)),
            ma_10=float(latest.get('MA_10', 0)),
            ma_20=float(latest.get('MA_20', 0)),
            ma_50=float(latest.get('MA_50', 0)),
            ma_200=float(latest.get('MA_200', 0)),
            rsi_14=float(latest.get('RSI_14', 0)),
            macd=float(latest.get('MACD', 0)),
            macd_signal=float(latest.get('MACD_signal', 0)),
            macd_histogram=float(latest.get('MACD_histogram', 0)),
            atr_14=float(latest.get('ATR_14', 0)),
            bb_upper=float(latest.get('BB_upper', 0)),
            bb_middle=float(latest.get('BB_middle', 0)),
            bb_lower=float(latest.get('BB_lower', 0)),
            volume_sma_20=int(latest.get('Volume_SMA_20', 0)),
            obv=int(latest.get('OBV', 0)),
        )
        
        self.session.add(indicator)
        await self.session.commit()
    
    async def _build_technical_analysis(
        self,
        symbol: str,
        indicators: Dict
    ) -> TechnicalAnalysisDTO:
        """构建技术分析结果"""
        # 获取历史数据用于趋势和支撑阻力分析
        df = await self.market_provider.get_historical_data(symbol, period="6mo")
        df = self.calculator.calculate_all_indicators(df)
        
        # 识别趋势
        trend_direction, trend_strength = self.calculator.identify_trend(df)
        
        # RSI分析
        rsi_value = indicators.get('RSI_14', 50)
        rsi_status, rsi_signal = self.calculator.identify_rsi_status(rsi_value)
        
        # MACD分析
        macd_signal = self.calculator.identify_macd_signal(df)
        
        # 布林带分析
        current_price = indicators['Close']
        bb_position = self.calculator.calculate_bollinger_position(
            current_price,
            indicators.get('BB_upper', 0),
            indicators.get('BB_middle', 0),
            indicators.get('BB_lower', 0)
        )
        
        # 支撑阻力位
        support_levels, resistance_levels = self.calculator.identify_support_resistance(df)
        
        # 生成AI总结
        ai_summary = self._generate_ai_summary(
            trend_direction, trend_strength, rsi_status, macd_signal, bb_position
        )
        
        return TechnicalAnalysisDTO(
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            description=f"{trend_direction} trend with {trend_strength}% strength",
            rsi=TechnicalAnalysisDTO.RSI(
                value=rsi_value,
                status=rsi_status,
                signal=rsi_signal
            ),
            macd=TechnicalAnalysisDTO.MACD(
                value=indicators.get('MACD', 0),
                signal_line=indicators.get('MACD_signal', 0),
                histogram=indicators.get('MACD_histogram', 0),
                status=macd_signal
            ),
            bollinger_bands=TechnicalAnalysisDTO.BollingerBands(
                upper=indicators.get('BB_upper', 0),
                middle=indicators.get('BB_middle', 0),
                lower=indicators.get('BB_lower', 0),
                current_price=current_price,
                position=bb_position,
                width_percentile=65  # TODO: 实际计算
            ),
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            ai_summary=ai_summary
        )
    
    def _generate_ai_summary(
        self,
        trend: str,
        strength: int,
        rsi_status: str,
        macd_signal: str,
        bb_position: str
    ) -> str:
        """生成AI总结"""
        summary_parts = []
        
        if trend == "BULLISH":
            summary_parts.append(f"技术面偏多，{strength}%趋势强度")
        elif trend == "BEARISH":
            summary_parts.append(f"技术面偏空，{strength}%趋势强度")
        else:
            summary_parts.append("技术面震荡，无明确方向")
        
        if rsi_status == "OVERSOLD":
            summary_parts.append("RSI超卖，可能反弹")
        elif rsi_status == "OVERBOUGHT":
            summary_parts.append("RSI超买，注意回调风险")
        
        if macd_signal == "BULLISH_CROSSOVER":
            summary_parts.append("MACD金叉确认")
        elif macd_signal == "BEARISH_CROSSOVER":
            summary_parts.append("MACD死叉，注意风险")
        
        return "，".join(summary_parts)
