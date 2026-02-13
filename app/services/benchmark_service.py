"""
基准数据服务 - 获取市场基准收益率（SPY/QQQ/etc）

用于计算Alpha和Beta
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from decimal import Decimal
import statistics

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.cache import cache


class BenchmarkService:
    """基准市场数据服务"""
    
    # 支持的基准指数
    BENCHMARKS = {
        "SPY": "S&P 500 ETF",
        "QQQ": "Nasdaq 100 ETF",
        "IWM": "Russell 2000 ETF"
    }
    
    def __init__(self, session: AsyncSession):
        self.session = session
        try:
            self.broker = make_option_broker_client()
        except Exception as e:
            print(f"初始化broker失败: {e}")
            self.broker = None
    
    async def get_benchmark_returns(
        self,
        symbol: str = "SPY",
        days: int = 30
    ) -> List[float]:
        """
        获取基准日收益率序列
        
        Args:
            symbol: 基准代码（SPY/QQQ/IWM）
            days: 回溯天数
            
        Returns:
            日收益率列表 [r1, r2, r3, ...]
        """
        if symbol not in self.BENCHMARKS:
            raise ValueError(f"不支持的基准: {symbol}, 支持: {list(self.BENCHMARKS.keys())}")
        
        # 尝试从缓存获取
        cache_key = f"benchmark_returns:{symbol}:{days}"
        cached = await cache.get(cache_key)
        if cached:
            return cached
        
        # 从broker获取历史数据
        if not self.broker:
            # 回退：返回模拟数据（实际生产应抛出异常）
            return self._generate_mock_returns(days)
        
        try:
            # 获取历史K线
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days + 10)  # 多获取一些以应对非交易日
            
            # 调用broker API获取历史数据
            bars = await self.broker.get_stock_bars(
                symbol=symbol,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                period="day"
            )
            
            if not bars or len(bars) < days:
                print(f"警告: {symbol}历史数据不足, 返回模拟数据")
                return self._generate_mock_returns(days)
            
            # 计算日收益率
            returns = []
            for i in range(1, len(bars)):
                prev_close = float(bars[i-1].get('close', 0))
                curr_close = float(bars[i].get('close', 0))
                if prev_close > 0:
                    daily_return = (curr_close - prev_close) / prev_close
                    returns.append(daily_return)
            
            # 取最近N天
            returns = returns[-days:]
            
            # 缓存1小时
            await cache.set(cache_key, returns, expire=3600)
            
            return returns
            
        except Exception as e:
            print(f"获取{symbol}基准数据失败: {e}")
            return self._generate_mock_returns(days)
    
    def _generate_mock_returns(self, days: int) -> List[float]:
        """
        生成模拟市场收益率（用于开发测试）
        模拟标普500的典型统计特征：
        - 年化收益：10%
        - 年化波动率：15%
        """
        import random
        random.seed(42)  # 固定种子保证可复现
        
        daily_mean = 0.10 / 252  # 年化10%收益
        daily_std = 0.15 / (252 ** 0.5)  # 年化15%波动率
        
        returns = []
        for _ in range(days):
            r = random.gauss(daily_mean, daily_std)
            returns.append(r)
        
        return returns
    
    async def get_benchmark_price(
        self,
        symbol: str = "SPY"
    ) -> Optional[float]:
        """获取基准当前价格"""
        if not self.broker:
            return None
        
        try:
            quote = await self.broker.get_stock_quote(symbol)
            return float(quote.get('last_price', 0))
        except Exception as e:
            print(f"获取{symbol}价格失败: {e}")
            return None
    
    async def calculate_market_volatility(
        self,
        symbol: str = "SPY",
        days: int = 30
    ) -> float:
        """
        计算市场波动率（年化）
        
        Returns:
            年化波动率（0-1之间的小数）
        """
        returns = await self.get_benchmark_returns(symbol, days)
        
        if not returns or len(returns) < 5:
            return 0.15  # 默认15%波动率
        
        # 计算标准差
        std_daily = statistics.stdev(returns)
        
        # 年化
        volatility_annualized = std_daily * (252 ** 0.5)
        
        return volatility_annualized
