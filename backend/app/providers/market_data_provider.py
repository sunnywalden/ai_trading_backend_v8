"""市场数据提供者 - 使用yfinance获取实时和历史数据"""
import yfinance as yf
import pandas as pd
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from functools import lru_cache


class MarketDataProvider:
    """市场数据提供者"""
    
    def __init__(self):
        self.cache_duration = 300  # 5分钟缓存
    
    @lru_cache(maxsize=100)
    def get_ticker(self, symbol: str) -> yf.Ticker:
        """获取ticker对象（带缓存）"""
        return yf.Ticker(symbol)
    
    async def get_historical_data(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d"
    ) -> pd.DataFrame:
        """获取历史数据
        
        Args:
            symbol: 股票代码
            period: 时间周期 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: 时间间隔 (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
        """
        ticker = self.get_ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        return df
    
    async def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        ticker = self.get_ticker(symbol)
        info = ticker.info
        return info.get('currentPrice') or info.get('regularMarketPrice', 0.0)
    
    async def get_quote(self, symbol: str) -> Dict:
        """获取实时报价"""
        ticker = self.get_ticker(symbol)
        info = ticker.info
        
        return {
            'symbol': symbol,
            'current_price': info.get('currentPrice', 0.0),
            'previous_close': info.get('previousClose', 0.0),
            'open': info.get('open', 0.0),
            'day_high': info.get('dayHigh', 0.0),
            'day_low': info.get('dayLow', 0.0),
            'volume': info.get('volume', 0),
            'avg_volume': info.get('averageVolume', 0),
            'market_cap': info.get('marketCap', 0),
            'timestamp': datetime.now()
        }
    
    async def get_company_info(self, symbol: str) -> Dict:
        """获取公司基本信息"""
        ticker = self.get_ticker(symbol)
        info = ticker.info
        
        return {
            'symbol': symbol,
            'name': info.get('longName', ''),
            'sector': info.get('sector', ''),
            'industry': info.get('industry', ''),
            'country': info.get('country', ''),
            'website': info.get('website', ''),
            'description': info.get('longBusinessSummary', ''),
            'employees': info.get('fullTimeEmployees', 0),
        }
    
    async def get_financials(self, symbol: str) -> Dict:
        """获取财务数据"""
        ticker = self.get_ticker(symbol)
        
        return {
            'income_statement': ticker.financials,
            'balance_sheet': ticker.balance_sheet,
            'cash_flow': ticker.cashflow,
            'quarterly_financials': ticker.quarterly_financials,
            'quarterly_balance_sheet': ticker.quarterly_balance_sheet,
            'quarterly_cashflow': ticker.quarterly_cashflow,
        }
    
    async def get_key_statistics(self, symbol: str) -> Dict:
        """获取关键统计数据"""
        ticker = self.get_ticker(symbol)
        info = ticker.info
        
        return {
            'pe_ratio': info.get('trailingPE'),
            'forward_pe': info.get('forwardPE'),
            'peg_ratio': info.get('pegRatio'),
            'pb_ratio': info.get('priceToBook'),
            'ps_ratio': info.get('priceToSalesTrailing12Months'),
            'price_to_book': info.get('priceToBook'),
            'roe': info.get('returnOnEquity'),
            'roa': info.get('returnOnAssets'),
            'profit_margin': info.get('profitMargins'),
            'operating_margin': info.get('operatingMargins'),
            'revenue_growth': info.get('revenueGrowth'),
            'earnings_growth': info.get('earningsGrowth'),
            'debt_to_equity': info.get('debtToEquity'),
            'current_ratio': info.get('currentRatio'),
            'quick_ratio': info.get('quickRatio'),
            'free_cash_flow': info.get('freeCashflow'),
            'operating_cash_flow': info.get('operatingCashflow'),
            'beta': info.get('beta'),
            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
            'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
        }
    
    async def get_analyst_recommendations(self, symbol: str) -> pd.DataFrame:
        """获取分析师评级"""
        ticker = self.get_ticker(symbol)
        return ticker.recommendations
    
    async def get_institutional_holders(self, symbol: str) -> pd.DataFrame:
        """获取机构持仓"""
        ticker = self.get_ticker(symbol)
        return ticker.institutional_holders
    
    async def get_options_data(self, symbol: str) -> Dict:
        """获取期权数据"""
        ticker = self.get_ticker(symbol)
        
        try:
            expirations = ticker.options
            if not expirations:
                return {}
            
            # 获取最近到期的期权链
            nearest_expiry = expirations[0]
            opt_chain = ticker.option_chain(nearest_expiry)
            
            return {
                'calls': opt_chain.calls,
                'puts': opt_chain.puts,
                'expiration_dates': expirations,
            }
        except Exception as e:
            print(f"Error fetching options for {symbol}: {e}")
            return {}
    
    async def batch_get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """批量获取报价"""
        quotes = {}
        for symbol in symbols:
            try:
                quotes[symbol] = await self.get_quote(symbol)
            except Exception as e:
                print(f"Error fetching quote for {symbol}: {e}")
                quotes[symbol] = None
        return quotes
