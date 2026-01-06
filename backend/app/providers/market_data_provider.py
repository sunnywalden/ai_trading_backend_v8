"""市场数据提供者

优先使用 Tiger OpenAPI (tigeropen QuoteClient) 获取行情与日线K线。
如果未配置 Tiger（TIGER_PRIVATE_KEY_PATH / TIGER_ID），则回退到 yfinance，保证开发/测试可运行。
"""

import pandas as pd
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from functools import lru_cache

from app.core.config import settings

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

try:
    from tigeropen.tiger_open_config import get_client_config
    from tigeropen.quote.quote_client import QuoteClient
    from tigeropen.common.consts import BarPeriod
except Exception:  # pragma: no cover
    get_client_config = None
    QuoteClient = None
    BarPeriod = None

import asyncio
from concurrent.futures import ThreadPoolExecutor


class MarketDataProvider:
    """市场数据提供者"""
    
    def __init__(self):
        self.cache_duration = 300  # 5分钟缓存
        self._tiger_quote_client = None
        self._executor = ThreadPoolExecutor(max_workers=4)

        if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID and get_client_config and QuoteClient:
            try:
                client_config = get_client_config(
                    private_key_path=settings.TIGER_PRIVATE_KEY_PATH,
                    tiger_id=settings.TIGER_ID,
                    account=settings.TIGER_ACCOUNT,
                )
                self._tiger_quote_client = QuoteClient(client_config)
            except Exception:
                # 初始化失败则回退到 yfinance
                self._tiger_quote_client = None

    async def _run_in_executor(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        if kwargs:
            return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))
        return await loop.run_in_executor(self._executor, func, *args)

    def _period_to_limit(self, period: str) -> int:
        """将 yfinance 风格的 period 映射为 Tiger bars limit（按交易日粗略估算）"""
        mapping = {
            "1d": 1,
            "5d": 5,
            "1mo": 22,
            "3mo": 66,
            "6mo": 132,
            "1y": 260,
            "2y": 520,
            "5y": 1300,
            "10y": 2600,
            "ytd": 260,
            "max": 2600,
        }
        return int(mapping.get((period or "1y").lower(), 260))
    
    @lru_cache(maxsize=100)
    def get_ticker(self, symbol: str):
        """获取ticker对象（带缓存）"""
        if yf is None:
            raise RuntimeError("yfinance not available")
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
        # Tiger优先：当前仅实现日线（1d）
        if self._tiger_quote_client and interval in ("1d", "1D", "day", "DAY") and BarPeriod is not None:
            end_ms = int(datetime.now().timestamp() * 1000)
            limit = self._period_to_limit(period)

            bars_df = await self._run_in_executor(
                self._tiger_quote_client.get_bars,
                [symbol],
                period=BarPeriod.DAY,
                end_time=end_ms,
                limit=limit,
            )

            if bars_df is None or len(bars_df) == 0:
                return pd.DataFrame()

            df = bars_df.copy()
            # Tiger 返回列名通常为 time/open/high/low/close/volume/symbol
            colmap = {
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
                "time": "Time",
            }
            for k, v in colmap.items():
                if k in df.columns and v not in df.columns:
                    df.rename(columns={k: v}, inplace=True)

            if "Time" in df.columns:
                df.index = pd.to_datetime(df["Time"], unit="ms")
                df.drop(columns=["Time"], inplace=True)

            # 如果是多symbol返回，过滤
            if "symbol" in df.columns:
                df = df[df["symbol"] == symbol].drop(columns=["symbol"], errors="ignore")

            # 统一列名风格
            for need in ["Open", "High", "Low", "Close", "Volume"]:
                if need not in df.columns:
                    df[need] = pd.NA
            df.sort_index(inplace=True)
            return df

        # fallback: yfinance
        ticker = self.get_ticker(symbol)
        return ticker.history(period=period, interval=interval)
    
    async def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        if self._tiger_quote_client:
            try:
                df = await self._run_in_executor(self._tiger_quote_client.get_stock_briefs, [symbol])
                if df is not None and len(df) > 0:
                    # tiger briefs: latest_price 或 close
                    row = df.iloc[0]
                    for key in ("latest_price", "latestPrice", "close", "pre_close"):
                        if key in row and row[key] is not None:
                            return float(row[key])
            except Exception:
                pass

        ticker = self.get_ticker(symbol)
        info = ticker.info
        return info.get('currentPrice') or info.get('regularMarketPrice', 0.0)
    
    async def get_quote(self, symbol: str) -> Dict:
        """获取实时报价"""
        if self._tiger_quote_client:
            try:
                df = await self._run_in_executor(self._tiger_quote_client.get_stock_briefs, [symbol])
                if df is not None and len(df) > 0:
                    row = df.iloc[0]
                    return {
                        "symbol": symbol,
                        "current_price": float(row.get("latest_price") or row.get("latestPrice") or 0.0),
                        "previous_close": float(row.get("pre_close") or row.get("preClose") or 0.0),
                        "open": float(row.get("open") or 0.0),
                        "day_high": float(row.get("high") or row.get("day_high") or 0.0),
                        "day_low": float(row.get("low") or row.get("day_low") or 0.0),
                        "volume": int(row.get("volume") or 0),
                        "avg_volume": int(row.get("avg_volume") or 0),
                        "market_cap": float(row.get("market_cap") or 0.0),
                        "timestamp": datetime.now(),
                        "source": "tiger",
                    }
            except Exception:
                pass

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
            'timestamp': datetime.now(),
            'source': 'yfinance'
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
