"""
低波动率策略
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import statistics

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.strategies.base_strategy import BaseStrategy
from app.providers.market_data_provider import MarketDataProvider


class LowVolatility(BaseStrategy):
    """
    低波动率策略（防御型）
    
    策略逻辑：
    - 选择低波动率（低Beta）的股票构建组合
    - 目标Beta < 0.6
    - 适合震荡市和熊市
    """
    
    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        signals = []
        
        # 获取参数
        max_beta = self.get_param("max_beta", 0.6)
        max_volatility = self.get_param("max_volatility", 0.15)  # 15%年化波动率
        lookback_days = self.get_param("lookback_days", 252)  # 一年
        top_n = self.get_param("top_n", 10)  # 选择前10只
        
        if not universe:
            universe = await self._get_default_universe()
        
        market_data = MarketDataProvider()
        
        candidates = []
        
        for symbol in universe:
            try:
                # 获取历史价格
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=lookback_days + 30)
                
                prices = await market_data.get_historical_prices(
                    symbol, start_date, end_date
                )
                
                if len(prices) < lookback_days:
                    continue
                
                # 计算日收益率
                returns = []
                for i in range(1, len(prices)):
                    ret = (prices[i]["close"] - prices[i-1]["close"]) / prices[i-1]["close"]
                    returns.append(ret)
                
                # 计算波动率（年化）
                volatility = statistics.stdev(returns) * (252 ** 0.5) if returns else 999
                
                # 计算Beta（简化版本，相对SPY）
                spy_prices = await market_data.get_historical_prices(
                    "SPY", start_date, end_date
                )
                
                if len(spy_prices) >= lookback_days:
                    spy_returns = []
                    for i in range(1, len(spy_prices)):
                        ret = (spy_prices[i]["close"] - spy_prices[i-1]["close"]) / spy_prices[i-1]["close"]
                        spy_returns.append(ret)
                    
                    # 计算协方差和方差
                    if len(returns) == len(spy_returns):
                        covariance = sum((r - sum(returns)/len(returns)) * (s - sum(spy_returns)/len(spy_returns)) 
                                       for r, s in zip(returns, spy_returns)) / len(returns)
                        spy_variance = sum((s - sum(spy_returns)/len(spy_returns))**2 for s in spy_returns) / len(spy_returns)
                        beta = covariance / spy_variance if spy_variance > 0 else 1.0
                    else:
                        beta = 1.0
                else:
                    beta = 1.0
                
                # 筛选低波动标的
                if beta < max_beta and volatility < max_volatility:
                    candidates.append({
                        "symbol": symbol,
                        "beta": beta,
                        "volatility": volatility,
                        "current_price": prices[-1]["close"],
                    })
                    
            except Exception as e:
                print(f"Error processing {symbol}: {e}")
                continue
        
        # 按波动率排序，选择最低的N只
        candidates.sort(key=lambda x: x["volatility"])
        top_candidates = candidates[:top_n]
        
        # 生成信号
        for candidate in top_candidates:
            signal = {
                "symbol": candidate["symbol"],
                "direction": "BUY",
                "strength": 70,  # 防御型策略稳定信号
                "weight": 1.0 / len(top_candidates),  # 等权分配
                "risk_score": 25,  # 低风险
                "target_price": float(candidate["current_price"] * 1.08),  # 8%目标
                "stop_loss": float(candidate["current_price"] * 0.95),  # 5%止损
                "metadata": {
                    "strategy": "low_volatility",
                    "entry_price": candidate["current_price"],
                    "beta": candidate["beta"],
                    "volatility": candidate["volatility"],
                }
            }
            signals.append(signal)
        
        return signals
    
    async def _get_default_universe(self) -> List[str]:
        """获取默认的标的池 - 包含防御性行业"""
        return [
            # 公用事业
            "NEE", "DUK", "SO", "D",
            # 必需消费品
            "PG", "KO", "PEP", "WMT", "COST",
            # 医疗保健
            "JNJ", "UNH", "PFE", "ABBV", "TMO",
            # 其他防御性股票
            "VZ", "T", "PM", "MO"
        ]
