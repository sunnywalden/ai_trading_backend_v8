"""
突破动量策略
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.strategies.base_strategy import BaseStrategy
from app.models.technical_indicator import TechnicalIndicator
from app.providers.market_data_provider import MarketDataProvider


class BreakoutMomentum(BaseStrategy):
    """
    突破动量策略
    
    策略逻辑：
    - 价格突破N日高点做多
    - 配合成交量放大确认
    - ATR作为止损位
    """
    
    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        signals = []
        
        # 获取参数
        lookback_days = self.get_param("lookback_days", 20)
        volume_multiplier = self.get_param("volume_multiplier", 1.5)
        atr_multiplier = self.get_param("atr_multiplier", 2.0)
        
        if not universe:
            universe = await self._get_default_universe()
        
        market_data = MarketDataProvider()
        
        for symbol in universe:
            try:
                # 获取历史价格数据
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=lookback_days + 30)
                
                prices = await market_data.get_historical_prices(
                    symbol, start_date, end_date
                )
                
                if len(prices) < lookback_days:
                    continue
                
                # 获取当前价格和成交量
                current_price = prices[-1]["close"]
                current_volume = prices[-1]["volume"]
                
                # 计算N日最高价
                high_prices = [p["high"] for p in prices[-lookback_days:-1]]
                n_day_high = max(high_prices)
                
                # 计算平均成交量
                avg_volume = sum(p["volume"] for p in prices[-lookback_days:-1]) / (lookback_days - 1)
                
                # 获取ATR指标
                stmt = select(TechnicalIndicator).where(
                    and_(
                        TechnicalIndicator.symbol == symbol,
                        TechnicalIndicator.indicator_type == "atr"
                    )
                ).order_by(TechnicalIndicator.timestamp.desc()).limit(1)
                
                result = await self.session.execute(stmt)
                atr_data = result.scalars().first()
                
                atr_value = atr_data.value.get("atr") if atr_data else current_price * 0.02
                
                # 突破判断
                is_breakout = current_price > n_day_high
                volume_confirmed = current_volume > avg_volume * volume_multiplier
                
                if is_breakout and volume_confirmed:
                    # 计算信号强度
                    breakout_pct = (current_price - n_day_high) / n_day_high * 100
                    volume_ratio = current_volume / avg_volume
                    strength = min(100, 60 + breakout_pct * 20 + volume_ratio * 10)
                    
                    signal = {
                        "symbol": symbol,
                        "direction": "BUY",
                        "strength": int(strength),
                        "weight": 1.0,
                        "risk_score": 55,  # 动量策略中等风险
                        "target_price": float(current_price * 1.10),  # 10%目标
                        "stop_loss": float(current_price - atr_value * atr_multiplier),
                        "metadata": {
                            "strategy": "breakout_momentum",
                            "entry_price": current_price,
                            "n_day_high": n_day_high,
                            "breakout_pct": breakout_pct,
                            "volume_ratio": volume_ratio,
                            "atr": atr_value,
                        }
                    }
                    signals.append(signal)
                    
            except Exception as e:
                print(f"Error processing {symbol}: {e}")
                continue
        
        return signals
    
    async def _get_default_universe(self) -> List[str]:
        """获取默认的标的池"""
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
            "META", "NVDA", "JPM", "V", "JNJ",
            "WMT", "PG", "MA", "HD", "DIS"
        ]
