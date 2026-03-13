"""
黄金交叉策略
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.engine.strategies.base_strategy import BaseStrategy
from app.models.technical_indicator import TechnicalIndicator
from app.providers.market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class GoldenCross(BaseStrategy):
    """
    黄金交叉策略（趋势跟踪）
    
    策略逻辑：
    - 短期均线上穿长期均线做多（Golden Cross）
    - 短期均线下穿长期均线做空（Death Cross）
    - 配合成交量和MACD确认
    """
    
    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        signals = []
        
        # 获取参数
        short_period = self.get_param("short_period", 50)
        long_period = self.get_param("long_period", 200)
        volume_confirm = self.get_param("volume_confirm", True)
        
        if not universe:
            universe = await self._get_default_universe()
        
        market_data = MarketDataProvider()
        
        for symbol in universe:
            try:
                # TechnicalIndicator 当前为扁平列模型（ma_50/ma_200/macd/macd_signal），
                # 不再是老的 indicator_type + value 结构。
                stmt = (
                    select(TechnicalIndicator)
                    .where(TechnicalIndicator.symbol == symbol, TechnicalIndicator.timeframe == "1D")
                    .order_by(TechnicalIndicator.timestamp.desc())
                    .limit(1)
                )

                result = await self.session.execute(stmt)
                indicator = result.scalars().first()

                if not indicator:
                    continue

                sma_50 = float(indicator.ma_50 or 0.0)
                sma_200 = float(indicator.ma_200 or 0.0)
                macd_value = float(indicator.macd or 0.0)
                signal_line = float(indicator.macd_signal or 0.0)
                
                if not sma_50 or not sma_200:
                    continue
                
                # 获取当前价格
                current_price = await market_data.get_latest_price(symbol)
                if not current_price:
                    continue
                
                # 判断交叉状态
                is_golden_cross = sma_50 > sma_200 and current_price > sma_50
                is_death_cross = sma_50 < sma_200 and current_price < sma_50
                
                # MACD确认
                macd_confirm = True
                if macd_value or signal_line:
                    macd_confirm = (is_golden_cross and macd_value > signal_line) or \
                                  (is_death_cross and macd_value < signal_line)
                
                if is_golden_cross and macd_confirm:
                    # 黄金交叉 - 做多信号
                    spread_pct = (sma_50 - sma_200) / sma_200 * 100
                    strength = min(100, 60 + abs(spread_pct) * 5)
                    
                    signal = {
                        "symbol": symbol,
                        "direction": "BUY",
                        "strength": int(strength),
                        "weight": 1.0,
                        "risk_score": 45,
                        "target_price": float(current_price * 1.15),  # 15%目标
                        "stop_loss": float(sma_200),  # 200日均线作为止损
                        "metadata": {
                            "strategy": "golden_cross",
                            "entry_price": current_price,
                            "sma_50": sma_50,
                            "sma_200": sma_200,
                            "cross_type": "golden",
                        }
                    }
                    signals.append(signal)
                
                elif is_death_cross and macd_confirm:
                    # 死亡交叉 - 做空信号
                    spread_pct = (sma_200 - sma_50) / sma_50 * 100
                    strength = min(100, 60 + abs(spread_pct) * 5)
                    
                    signal = {
                        "symbol": symbol,
                        "direction": "SELL",
                        "strength": int(strength),
                        "weight": 1.0,
                        "risk_score": 50,
                        "target_price": float(current_price * 0.85),  # 15%目标
                        "stop_loss": float(sma_200),
                        "metadata": {
                            "strategy": "golden_cross",
                            "entry_price": current_price,
                            "sma_50": sma_50,
                            "sma_200": sma_200,
                            "cross_type": "death",
                        }
                    }
                    signals.append(signal)
                    
            except Exception as e:
                logger.debug("GoldenCross processing failed for %s: %s", symbol, e)
                continue
        
        return signals
    
    async def _get_default_universe(self) -> List[str]:
        """获取默认的标的池"""
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
            "META", "NVDA", "JPM", "V", "JNJ",
            "SPY", "QQQ", "DIA", "IWM"  # 包含ETF
        ]
