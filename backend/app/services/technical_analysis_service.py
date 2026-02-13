"""技术分析服务"""
import logging
from typing import Dict, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from datetime import datetime, date
import json

logger = logging.getLogger(__name__)

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
        account_id: str = "DEMO",
        pre_fetched_df=None,
        use_ai: bool = True
    ) -> TechnicalAnalysisDTO:
        """获取技术分析（改进：支持重用已拉取的K线并可禁用AI以降低延迟）
        
        Args:
            symbol: 股票代码
            timeframe: 时间框架
            use_cache: 是否使用缓存
            pre_fetched_df: 如果传入已拉取并计算过的 DataFrame，可避免重复网络请求
            use_ai: 是否调用AI生成总结（刷新场景可禁用）
        """
        # 1. 尝试从缓存获取
        if use_cache:
            cached = await self._get_cached_indicators(symbol, timeframe)
            if cached:
                return await self._build_technical_analysis(
                    symbol, cached, timeframe, account_id, df=pre_fetched_df, use_ai=use_ai
                )
        
        # 2. 从市场获取最新数据（允许重用 pre_fetched_df）
        df = pre_fetched_df if pre_fetched_df is not None else await self.market_provider.get_historical_data(symbol, period="1y", interval="1d")
        
        if df is None or getattr(df, 'empty', True):
            raise ValueError(f"No data available for {symbol}")
        
        # 3. 计算所有技术指标（如果尚未计算）
        if 'MA_5' not in df.columns:
            df = self.calculator.calculate_all_indicators(df)
        
        # 4. 保存到缓存（不在每处都commit，统一由调用方控制commit频率）
        await self._save_indicators_to_cache(symbol, df, timeframe)
        
        # 5. 构建分析结果（传入完整的 df 以避免再次拉取）
        result = await self._build_technical_analysis(
            symbol,
            df.iloc[-1].to_dict(),
            timeframe,
            account_id,
            df=df,
            use_ai=use_ai
        )

        # 6. 确保把缓存更新写入数据库（兼容旧行为：单次调用时提交）
        try:
            await self.session.commit()
        except Exception:
            # 部分调用场景可能传入的session不允许commit，这里忽略错误以保持兼容性
            pass

        return result
    
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
        
        # 注意：不在此处 commit，调用方负责在合适时机统一 commit 以减少数据库压力
        

    

    async def needs_refresh(self, symbol: str, timeframe: str = "1D", force: bool = False) -> bool:
        """判断是否需要刷新技术数据（当无今日缓存或强制刷新时返回 True）"""
        if force:
            return True
        cached = await self._get_cached_indicators(symbol, timeframe)
        return cached is None
        
    async def _build_technical_analysis(
        self,
        symbol: str,
        indicators: Dict,
        timeframe: str,
        account_id: str,
        df=None,
        use_ai: bool = True
    ) -> TechnicalAnalysisDTO:
        """构建技术分析结果（支持传入预计算的 df 并可禁用 AI）"""
        # 确保 df 已包含必要的历史数据与指标
        if df is None:
            df = await self.market_provider.get_historical_data(symbol, period="6mo")
            df = self.calculator.calculate_all_indicators(df)
        else:
            if 'MA_5' not in df.columns:
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

        # 生成AI总结（可禁用）：优先调用OpenAI（基于日线走势/指标给出结论），失败则尝试获取历史记录
        ai_summary = None
        if use_ai:
            try:
                from app.services.ai_analysis_service import AIAnalysisService
                
                # 构建 payload 给 AI 分析
                payload = {
                    "timeframe": timeframe,
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
                    },
                    "levels": {
                        "support": support_levels[0] if support_levels else None,
                        "resistance": resistance_levels[0] if resistance_levels else None,
                    },
                    "stats": {
                        "return_5d": None,  # 可后续补充
                        "return_20d": None,
                        "vol_20d": None,
                    },
                    "recent_ohlcv": df.tail(10)[['Open', 'High', 'Low', 'Close', 'Volume']].to_dict(orient='records') if not df.empty else [],
                }
                
                ai_service = AIAnalysisService()
                ai_summary = await ai_service.generate_daily_trend_conclusion(symbol, payload)
            except Exception as e:
                logger.warning(f"AI trend conclusion failed for {symbol}: {e}. Trying to fetch historical summary.")
                ai_summary = None
        
        # 降级策略：如果 AI 生成失败，尝试从历史快照中找一个已有的 AI 总结
        if not ai_summary:
            historical_snap = await self.get_latest_trend_snapshot(symbol, account_id, timeframe, only_today=False)
            if historical_snap and historical_snap.ai_summary:
                ai_summary = f"[历史数据] {historical_snap.ai_summary}"
                logger.info(f"Using historical AI summary for {symbol}")

        # 如果还是没有，最后回退到规则引擎
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
        # 不在此处提交事务，由调用方统一 commit 以减少数据库压力

    async def get_latest_trend_snapshot(
        self,
        symbol: str,
        account_id: str = "DEMO",
        timeframe: str = "1D",
        only_today: bool = True
    ) -> Optional[PositionTrendSnapshot]:
        """获取最近一次的趋势快照
        
        Args:
            symbol: 股票代码
            account_id: 账户ID
            timeframe: 时间周期
            only_today: 是否仅限今天。如果为 False，则返回最新的一条记录（即便不是今天的）。
        """
        stmt = select(PositionTrendSnapshot).where(
            PositionTrendSnapshot.symbol == symbol,
            PositionTrendSnapshot.account_id == account_id,
            PositionTrendSnapshot.timeframe == timeframe
        )
        
        if only_today:
            today = date.today()
            stmt = stmt.where(
                PositionTrendSnapshot.timestamp >= datetime.combine(today, datetime.min.time())
            )
            
        stmt = stmt.order_by(PositionTrendSnapshot.timestamp.desc())

        result = await self.session.execute(stmt)
        return result.scalars().first()
