"""
布林带均值回归策略
"""
from typing import Any, Dict, List, Optional
import asyncio

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.strategies.base_strategy import BaseStrategy
from app.models.technical_indicator import TechnicalIndicator
from app.providers.market_data_provider import MarketDataProvider


class BollingerBandsMeanReversion(BaseStrategy):
    """
    布林带均值回归策略
    
    策略逻辑：
    - 价格突破下轨时做多（超卖信号）
    - 价格突破上轨时做空（超买信号）
    - 回归至中轨平仓
    """
    
    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        signals = []
        
        # 获取参数
        bb_period = self.get_param("bb_period", 20)
        bb_std = self.get_param("bb_std", 2.0)
        volume_threshold = self.get_param("volume_threshold", 1000000)
        
        # 如果没有指定universe，使用默认的常见股票池
        if not universe:
            universe = await self._get_default_universe()
        
        # 获取市场数据提供商
        market_data = MarketDataProvider()
        
        # 对每个标的进行分析
        for symbol in universe:
            try:
                # 获取最新的技术指标数据
                stmt = select(TechnicalIndicator).where(
                    and_(
                        TechnicalIndicator.symbol == symbol,
                        TechnicalIndicator.indicator_type == "bollinger_bands"
                    )
                ).order_by(TechnicalIndicator.timestamp.desc()).limit(1)
                
                result = await self.session.execute(stmt)
                bb_data = result.scalars().first()
                
                if not bb_data:
                    continue
                
                # 获取当前价格
                current_price = await market_data.get_latest_price(symbol)
                if not current_price:
                    continue
                
                # 解析布林带数据
                bb_values = bb_data.value or {}
                upper_band = bb_values.get("upper")
                middle_band = bb_values.get("middle")
                lower_band = bb_values.get("lower")
                
                if not all([upper_band, middle_band, lower_band]):
                    continue
                
                # 生成信号
                signal = None
                
                # 超卖 - 价格低于下轨
                if current_price < lower_band:
                    distance_pct = abs(current_price - lower_band) / lower_band * 100
                    signal = {
                        "symbol": symbol,
                        "direction": "BUY",
                        "strength": min(100, 50 + distance_pct * 10),  # 距离越远信号越强
                        "weight": 1.0,
                        "risk_score": 35,  # 均值回归策略相对低风险
                        "target_price": float(middle_band),
                        "stop_loss": float(current_price * 0.97),  # 3% 止损
                        "metadata": {
                            "strategy": "bollinger_mean_reversion",
                            "entry_price": current_price,
                            "upper_band": upper_band,
                            "middle_band": middle_band,
                            "lower_band": lower_band,
                            "oversold": True,
                        }
                    }
                
                # 超买 - 价格高于上轨
                elif current_price > upper_band:
                    distance_pct = abs(current_price - upper_band) / upper_band * 100
                    signal = {
                        "symbol": symbol,
                        "direction": "SELL",
                        "strength": min(100, 50 + distance_pct * 10),
                        "weight": 1.0,
                        "risk_score": 40,  # 做空风险略高
                        "target_price": float(middle_band),
                        "stop_loss": float(current_price * 1.03),  # 3% 止损
                        "metadata": {
                            "strategy": "bollinger_mean_reversion",
                            "entry_price": current_price,
                            "upper_band": upper_band,
                            "middle_band": middle_band,
                            "lower_band": lower_band,
                            "overbought": True,
                        }
                    }
                
                if signal:
                    signals.append(signal)
                    
            except Exception as e:
                # 记录错误但继续处理其他标的
                print(f"Error processing {symbol}: {e}")
                continue
        
        return signals
    
    async def _get_default_universe(self) -> List[str]:
        """获取默认的标的池"""
        # 返回一些常见的大盘股
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
            "META", "NVDA", "JPM", "V", "JNJ",
            "WMT", "PG", "MA", "HD", "DIS"
        ]
