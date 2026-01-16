"""技术分析服务"""
from typing import Dict, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from datetime import datetime, date
import json

from app.models.technical_indicator import TechnicalIndicator
from app.models.position_trend_snapshot import PositionTrendSnapshot
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
        use_cache: bool = True,
        account_id: str = "DEMO"
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
                return await self._build_technical_analysis(symbol, cached, timeframe, account_id)
        
        # 2. 从市场获取最新数据
        df = await self.market_provider.get_historical_data(symbol, period="1y", interval="1d")
        
        if df.empty:
            raise ValueError(f"No data available for {symbol}")
        
        # 3. 计算所有技术指标
        df = self.calculator.calculate_all_indicators(df)
        
        # 4. 保存到缓存
        await self._save_indicators_to_cache(symbol, df, timeframe)
        
        # 5. 构建分析结果
        return await self._build_technical_analysis(symbol, df.iloc[-1].to_dict(), timeframe, account_id)
    
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
        
        # 安全获取并转换值（处理 None/NaN）
        def safe_float(val, default=0.0):
            try:
                if val is None or (hasattr(val, '__iter__') and len(str(val)) == 0):
                    return default
                result = float(val)
                # 检测 NaN（numpy.nan 或 pandas NaN）
                if result != result:  # NaN != NaN 始终为 True
                    return default
                return result
            except (ValueError, TypeError):
                return default
        
        def safe_int(val, default=0):
            try:
                if val is None:
                    return default
                result = float(val)  # 先转 float 以处理 NaN
                if result != result:  # 检测 NaN
                    return default
                return int(result)
            except (ValueError, TypeError):
                return default
        
        # 先查询是否已存在相同的记录（按symbol+timeframe+今天的时间戳）
        from sqlalchemy import select, and_, func as sql_func
        from datetime import date
        
        stmt = select(TechnicalIndicator).where(
            and_(
                TechnicalIndicator.symbol == symbol,
                TechnicalIndicator.timeframe == timeframe,
                sql_func.date(TechnicalIndicator.timestamp) == date.today()
            )
        ).order_by(TechnicalIndicator.id.desc()).limit(1)
        
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # 更新现有记录
            existing.close_price = safe_float(latest.get('Close'))
            existing.volume = safe_int(latest.get('Volume'))
            existing.ma_5 = safe_float(latest.get('MA_5'))
            existing.ma_10 = safe_float(latest.get('MA_10'))
            existing.ma_20 = safe_float(latest.get('MA_20'))
            existing.ma_50 = safe_float(latest.get('MA_50'))
            existing.ma_200 = safe_float(latest.get('MA_200'))
            existing.rsi_14 = safe_float(latest.get('RSI_14'))
            existing.macd = safe_float(latest.get('MACD'))
            existing.macd_signal = safe_float(latest.get('MACD_signal'))
            existing.macd_histogram = safe_float(latest.get('MACD_histogram'))
            existing.atr_14 = safe_float(latest.get('ATR_14'))
            existing.bb_upper = safe_float(latest.get('BB_upper'))
            existing.bb_middle = safe_float(latest.get('BB_middle'))
            existing.bb_lower = safe_float(latest.get('BB_lower'))
            existing.volume_sma_20 = safe_int(latest.get('Volume_SMA_20'))
            existing.obv = safe_int(latest.get('OBV'))
            existing.timestamp = sql_func.now()  # 更新时间戳
        else:
            # 插入新记录
            indicator = TechnicalIndicator(
                symbol=symbol,
                timeframe=timeframe,
                close_price=safe_float(latest.get('Close')),
                volume=safe_int(latest.get('Volume')),
                ma_5=safe_float(latest.get('MA_5')),
                ma_10=safe_float(latest.get('MA_10')),
                ma_20=safe_float(latest.get('MA_20')),
                ma_50=safe_float(latest.get('MA_50')),
                ma_200=safe_float(latest.get('MA_200')),
                rsi_14=safe_float(latest.get('RSI_14')),
                macd=safe_float(latest.get('MACD')),
                macd_signal=safe_float(latest.get('MACD_signal')),
                macd_histogram=safe_float(latest.get('MACD_histogram')),
                atr_14=safe_float(latest.get('ATR_14')),
                bb_upper=safe_float(latest.get('BB_upper')),
                bb_middle=safe_float(latest.get('BB_middle')),
                bb_lower=safe_float(latest.get('BB_lower')),
                volume_sma_20=safe_int(latest.get('Volume_SMA_20')),
                obv=safe_int(latest.get('OBV')),
            )
            self.session.add(indicator)
        
        await self.session.commit()
    
    async def _build_technical_analysis(
        self,
        symbol: str,
        indicators: Dict,
        timeframe: str,
        account_id: str
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
        
        # 布林带分析 - 安全获取价格
        current_price = indicators.get('Close')
        if current_price is None or current_price == 0:
            # 尝试从 df 获取最后价格
            if not df.empty and 'Close' in df.columns:
                current_price = float(df.iloc[-1]['Close']) if df.iloc[-1].get('Close') else 0.0
            else:
                current_price = 0.0
        else:
            current_price = float(current_price)
        
        bb_position = self.calculator.calculate_bollinger_position(
            current_price,
            float(indicators.get('BB_upper') or 0),
            float(indicators.get('BB_middle') or 0),
            float(indicators.get('BB_lower') or 0)
        )
        
        # 支撑阻力位
        support_levels, resistance_levels = self.calculator.identify_support_resistance(df)
        
        latest_row = df.iloc[-1]
        volume_ratio = None
        volume_sma_20 = latest_row.get('Volume_SMA_20')
        current_volume = latest_row.get('Volume')
        if volume_sma_20 and volume_sma_20 > 0 and current_volume:
            volume_ratio = float(current_volume) / float(volume_sma_20)

        # 生成AI总结：优先调用OpenAI（基于日线走势/指标给出结论），失败则回退到规则摘要
        ai_summary = None
        try:
            from app.services.ai_analysis_service import AIAnalysisService

            # 压缩后的日线序列（避免token过大）：最近30根K线 + 关键统计
            recent = df.tail(30).copy()
            ohlcv = []
            for idx, row in recent.iterrows():
                ohlcv.append(
                    {
                        "date": str(getattr(idx, "date", lambda: idx)()),
                        "open": float(row.get("Open", 0) or 0),
                        "high": float(row.get("High", 0) or 0),
                        "low": float(row.get("Low", 0) or 0),
                        "close": float(row.get("Close", 0) or 0),
                        "volume": float(row.get("Volume", 0) or 0),
                    }
                )

            ret_5d = float(recent["Close"].pct_change(5).iloc[-1]) if "Close" in recent.columns and len(recent) > 6 else None
            ret_20d = float(recent["Close"].pct_change(20).iloc[-1]) if "Close" in recent.columns and len(recent) > 21 else None
            vol_20d = float(recent["Close"].pct_change().tail(20).std()) if "Close" in recent.columns and len(recent) > 21 else None

            payload = {
                "timeframe": timeframe,
                "source": "tiger_or_cache",
                "trend": {
                    "trend_direction": trend_direction,
                    "trend_strength": trend_strength,
                    "bollinger_position": bb_position,
                    "volume_ratio": volume_ratio,
                },
                "momentum": {
                    "rsi_value": rsi_value,
                    "rsi_status": rsi_status,
                    "macd_status": macd_signal,
                    "macd": float(indicators.get("MACD", 0) or 0),
                    "macd_signal": float(indicators.get("MACD_signal", 0) or 0),
                },
                "levels": {
                    "support": support_levels,
                    "resistance": resistance_levels,
                },
                "stats": {
                    "return_5d": ret_5d,
                    "return_20d": ret_20d,
                    "vol_20d": vol_20d,
                },
                "recent_ohlcv": ohlcv,
                "instructions": {
                    "style": "顶级华尔街交易员视角",
                    "constraints": ["不要输出任何趋势置信度/可信度数值"],
                },
            }

            ai_service = AIAnalysisService()
            ai_summary = await ai_service.generate_daily_trend_conclusion(symbol, payload)
        except Exception:
            ai_summary = None

        if not ai_summary:
            ai_summary = self._generate_ai_summary(
                trend_direction, trend_strength, rsi_status, macd_signal, bb_position
            )
        
        await self._save_trend_snapshot(
            symbol=symbol,
            timeframe=timeframe,
            account_id=account_id,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            trend_description=f"{trend_direction} trend with {trend_strength}% strength",
            rsi_value=rsi_value,
            rsi_status=rsi_status,
            macd_status=macd_signal,
            macd_signal=float(indicators.get('MACD', 0)),
            bollinger_position=bb_position,
            volume_ratio=volume_ratio,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            ai_summary=ai_summary
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
            ai_summary=ai_summary,
            volume_ratio=volume_ratio
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

    async def _save_trend_snapshot(
        self,
        symbol: str,
        timeframe: str,
        account_id: str,
        trend_direction: str,
        trend_strength: int,
        trend_description: str,
        rsi_value: float,
        rsi_status: str,
        macd_status: str,
        macd_signal: float,
        bollinger_position: str,
        volume_ratio: Optional[float],
        support_levels: List[float],
        resistance_levels: List[float],
        ai_summary: str
    ):
        """写入日线趋势快照缓存"""
        start_of_day = datetime.combine(date.today(), datetime.min.time())
        await self.session.execute(
            delete(PositionTrendSnapshot).where(
                PositionTrendSnapshot.symbol == symbol,
                PositionTrendSnapshot.account_id == account_id,
                PositionTrendSnapshot.timeframe == timeframe,
                PositionTrendSnapshot.timestamp >= start_of_day
            )
        )

        snapshot = PositionTrendSnapshot(
            account_id=account_id,
            symbol=symbol,
            timeframe=timeframe,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            trend_description=trend_description,
            rsi_value=rsi_value,
            rsi_status=rsi_status,
            macd_status=macd_status,
            macd_signal=macd_signal,
            bollinger_position=bollinger_position,
            volume_ratio=volume_ratio,
            support_levels=json.dumps(support_levels or []),
            resistance_levels=json.dumps(resistance_levels or []),
            ai_summary=ai_summary
        )

        self.session.add(snapshot)
        await self.session.commit()

    async def get_latest_trend_snapshot(
        self,
        symbol: str,
        account_id: str = "DEMO",
        timeframe: str = "1D"
    ) -> Optional[PositionTrendSnapshot]:
        """获取最近一次的趋势快照"""
        today = date.today()
        stmt = select(PositionTrendSnapshot).where(
            PositionTrendSnapshot.symbol == symbol,
            PositionTrendSnapshot.account_id == account_id,
            PositionTrendSnapshot.timeframe == timeframe,
            PositionTrendSnapshot.timestamp >= datetime.combine(today, datetime.min.time())
        ).order_by(PositionTrendSnapshot.timestamp.desc())

        result = await self.session.execute(stmt)
        return result.scalars().first()
