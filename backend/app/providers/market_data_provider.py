"""市场数据提供者

优先使用 Tiger OpenAPI (tigeropen QuoteClient) 获取行情与日线K线。
如果未配置 Tiger（TIGER_PRIVATE_KEY_PATH / TIGER_ID），则回退到 yfinance，保证开发/测试可运行。

缓存策略：
- Tiger K线数据：缓存5分钟（避免频繁请求）
- 价格数据：缓存1分钟
- Yahoo Finance数据：缓存1小时（备用数据源）
- 请求频率控制：每个symbol最多1秒1次请求
- Redis缓存增强：跨进程共享缓存
- API调用监控：跟踪调用频率和成功率
"""

import pandas as pd
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from functools import lru_cache
import time

from app.core.config import settings
from app.core.cache import cache
from app.services.api_monitoring_service import api_monitor, APIProvider

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
        self._ext_api_semaphore = asyncio.Semaphore(settings.EXTERNAL_API_CONCURRENCY)
        
        # K线数据缓存: {(symbol, period, interval): (data, timestamp)}
        self._bars_cache: Dict[tuple, tuple] = {}
        self._bars_cache_ttl = 300  # K线缓存5分钟
        
        # 价格数据缓存: {symbol: (price, timestamp)}
        self._price_cache: Dict[str, tuple] = {}
        self._price_cache_ttl = 60  # 价格缓存1分钟
        
        # 请求频率控制: 记录每个symbol的最后请求时间
        self._last_request_time: Dict[str, float] = {}
        self._request_min_interval = 1.0  # 每个symbol最少间隔1秒

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

    async def _run_external(self, func, *args, **kwargs):
        """外部API调用并发控制"""
        async with self._ext_api_semaphore:
            return await self._run_in_executor(func, *args, **kwargs)

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
        # 转换为Yahoo Finance格式
        yahoo_symbol = self._convert_to_yahoo_symbol(symbol)
        return yf.Ticker(yahoo_symbol)
    
    def _convert_to_yahoo_symbol(self, symbol: str) -> str:
        """将Tiger格式的symbol转换为Yahoo Finance格式
        
        Args:
            symbol: Tiger格式的股票代码（如02513、AAPL）
        
        Returns:
            Yahoo Finance格式的代码（如2513.HK、AAPL）
        """
        # 港股代码：5位数字，可能有前导0
        if len(symbol) >= 4 and symbol.isdigit():
            # 移除前导0
            numeric_symbol = str(int(symbol))
            return f"{numeric_symbol}.HK"
        # 其他市场直接返回
        return symbol
    
    async def get_historical_data(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d"
    ) -> pd.DataFrame:
        """获取历史数据 - Tiger优先, 带缓存和频率控制
        
        Args:
            symbol: 股票代码
            period: 时间周期 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: 时间间隔 (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
        """
        # 检查缓存
        cache_key = (symbol, period, interval)
        cached_data = self._get_cached_bars(cache_key)
        if cached_data is not None:
            print(f"[MarketData] Using cached bars for {symbol}")
            return cached_data
        
        # Tiger API优先（仅日线）
        if self._tiger_quote_client and interval in ("1d", "1D", "day", "DAY") and BarPeriod is not None:
            try:
                # 频率控制: 避免过于频繁的请求
                await self._wait_for_rate_limit(symbol)
                
                print(f"[MarketData] Attempting Tiger API for {symbol} (period={period})")
                df = await self._get_tiger_bars(symbol, period)
                
                if df is not None and len(df) > 0:
                    print(f"[MarketData] Tiger API success for {symbol}, rows={len(df)}")
                    # 缓存成功的数据
                    self._cache_bars(cache_key, df)
                    return df
                else:
                    print(f"[MarketData] Tiger API returned empty data for {symbol}")
            except Exception as e:
                print(f"[MarketData] Tiger API failed for {symbol}: {e}")
        
        # 降级到Yahoo Finance（增加延迟避免Rate Limit）
        print(f"[MarketData] Falling back to Yahoo Finance for {symbol}")
        df = await self._get_yahoo_data_with_retry(symbol, period, interval)
        
        if df is not None and len(df) > 0:
            # 缓存Yahoo数据（更长的TTL）
            self._cache_bars(cache_key, df, ttl=3600)  # 1小时
            return df
        
        # 返回空DataFrame
        print(f"[MarketData] All data sources failed for {symbol}")
        return pd.DataFrame()
    
    async def get_current_price(self, symbol: str) -> float:
        """获取当前价格 - Tiger优先, 带缓存"""
        # 检查缓存
        cached_price = self._get_cached_price(symbol)
        if cached_price is not None:
            print(f"[MarketData] Using cached price for {symbol}: {cached_price}")
            return cached_price
        
        # Tiger API优先
        if self._tiger_quote_client:
            try:
                await self._wait_for_rate_limit(symbol)
                print(f"[MarketData] Attempting Tiger API for price of {symbol}")
                
                df = await self._run_external(self._tiger_quote_client.get_stock_briefs, [symbol])
                if df is not None and len(df) > 0:
                    # tiger briefs: latest_price 或 close
                    row = df.iloc[0]
                    for key in ("latest_price", "latestPrice", "close", "pre_close"):
                        if key in row and row[key] is not None:
                            price = float(row[key])
                            print(f"[MarketData] Tiger price for {symbol}: {price}")
                            # 缓存价格
                            self._cache_price(symbol, price)
                            return price
            except Exception as e:
                print(f"[MarketData] Tiger API price failed for {symbol}: {e}")

        # Fallback to Yahoo Finance
        print(f"[MarketData] Falling back to Yahoo Finance for price of {symbol}")
        try:
            gate = await api_monitor.can_call_provider(APIProvider.YAHOO_FINANCE)
            if not gate.get("can_call", True):
                print(f"[MarketData] Skip Yahoo price due to cooldown/limit: {gate.get('reason')}")
                return 0.0
            ticker = self.get_ticker(symbol)
            info = ticker.info
            price = info.get('currentPrice') or info.get('regularMarketPrice', 0.0)
            if price > 0:
                self._cache_price(symbol, price)
            return price
        except Exception as e:
            print(f"[MarketData] Yahoo Finance price failed for {symbol}: {e}")
            return 0.0
    
    async def get_quote(self, symbol: str) -> Dict:
        """获取实时报价"""
        if self._tiger_quote_client:
            try:
                df = await self._run_external(self._tiger_quote_client.get_stock_briefs, [symbol])
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
    
    # ==================== 辅助方法 ====================
    
    async def _get_tiger_bars(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        """从Tiger API获取K线数据（带监控）"""
        start_time = time.time()
        success = False
        error_msg = None
        result = None
        
        try:
            end_ms = int(datetime.now().timestamp() * 1000)
            limit = self._period_to_limit(period)
            
            bars_df = await self._run_external(
                self._tiger_quote_client.get_bars,
                [symbol],
                period=BarPeriod.DAY,
                end_time=end_ms,
                limit=limit,
            )
            
            if bars_df is None or len(bars_df) == 0:
                error_msg = "Empty bars returned"
            elif len(bars_df) < 30:
                error_msg = f"Insufficient data: {len(bars_df)} rows < 30 days"
                print(f"[MarketData] Tiger API returned insufficient data for {symbol}: {len(bars_df)} rows < 30 days")
            else:
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
                
                # 如果是多symbol返回, 过滤
                if "symbol" in df.columns:
                    df = df[df["symbol"] == symbol].drop(columns=["symbol"], errors="ignore")
                
                # 统一列名风格
                for need in ["Open", "High", "Low", "Close", "Volume"]:
                    if need not in df.columns:
                        df[need] = pd.NA
                df.sort_index(inplace=True)
                result = df
                success = True
                
        except Exception as e:
            error_msg = str(e)
        
        # 记录API调用
        response_time = (time.time() - start_time) * 1000
        await api_monitor.record_api_call(
            provider=APIProvider.TIGER,
            endpoint=f"get_bars:{symbol}",
            success=success,
            response_time_ms=response_time,
            error_message=error_msg
        )
        
        return result
    
    async def _get_yahoo_data_with_retry(self, symbol: str, period: str, interval: str, max_retries: int = 1) -> Optional[pd.DataFrame]:
        """从Yahoo Finance获取数据（带监控，单次请求不重试）"""
        # 转换为Yahoo格式
        yahoo_symbol = self._convert_to_yahoo_symbol(symbol)

        gate = await api_monitor.can_call_provider(APIProvider.YAHOO_FINANCE)
        if not gate.get("can_call", True):
            print(f"[MarketData] Skip Yahoo Finance due to cooldown/limit: {gate.get('reason')}")
            return None
        
        start_time = time.time()
        success = False
        error_msg = None
        result = None
        
        try:
            ticker = yf.Ticker(yahoo_symbol) if yf else None
            if ticker is None:
                error_msg = "yfinance not available"
                print(f"[MarketData] yfinance not available")
            else:
                df = await self._run_external(ticker.history, period=period, interval=interval)
                if df is not None and len(df) > 0:
                    print(f"[MarketData] Yahoo Finance success for {symbol} ({yahoo_symbol}), rows={len(df)}")
                    result = df
                    success = True
                else:
                    error_msg = "Empty data returned"
                    print(f"[MarketData] Yahoo Finance returned empty data for {symbol}")
        except Exception as e:
            error_msg = str(e)
            if "Rate" in error_msg or "Too Many" in error_msg:
                print(f"[MarketData] Yahoo Finance rate limit for {symbol}: {error_msg}")
            else:
                print(f"[MarketData] Yahoo Finance failed for {symbol}: {error_msg}")
        
        # 记录API调用
        response_time = (time.time() - start_time) * 1000
        await api_monitor.record_api_call(
            provider=APIProvider.YAHOO_FINANCE,
            endpoint=f"history:{yahoo_symbol}",
            success=success,
            response_time_ms=response_time,
            error_message=error_msg
        )
        
        return result
    
    async def _wait_for_rate_limit(self, symbol: str):
        """频率控制: 确保每个symbol的请求间隔不小于_request_min_interval"""
        if symbol in self._last_request_time:
            elapsed = time.time() - self._last_request_time[symbol]
            if elapsed < self._request_min_interval:
                wait_time = self._request_min_interval - elapsed
                print(f"[MarketData] Rate limit wait {wait_time:.2f}s for {symbol}")
                await asyncio.sleep(wait_time)
        self._last_request_time[symbol] = time.time()
    
    def _get_cached_bars(self, cache_key: tuple) -> Optional[pd.DataFrame]:
        """获取缓存的K线数据"""
        if cache_key in self._bars_cache:
            data, timestamp = self._bars_cache[cache_key]
            if time.time() - timestamp < self._bars_cache_ttl:
                return data
            else:
                # 缓存过期, 删除
                del self._bars_cache[cache_key]
        return None
    
    def _cache_bars(self, cache_key: tuple, data: pd.DataFrame, ttl: Optional[int] = None):
        """缓存K线数据"""
        if ttl is None:
            ttl = self._bars_cache_ttl
        self._bars_cache[cache_key] = (data, time.time())
        # 简单LRU: 限制缓存大小
        if len(self._bars_cache) > 100:
            # 删除最旧的缓存项
            oldest_key = min(self._bars_cache.items(), key=lambda x: x[1][1])[0]
            del self._bars_cache[oldest_key]
    
    def _get_cached_price(self, symbol: str) -> Optional[float]:
        """获取缓存的价格"""
        if symbol in self._price_cache:
            price, timestamp = self._price_cache[symbol]
            if time.time() - timestamp < self._price_cache_ttl:
                return price
            else:
                del self._price_cache[symbol]
        return None
    
    def _cache_price(self, symbol: str, price: float):
        """缓存价格"""
        self._price_cache[symbol] = (price, time.time())
        # 简单LRU: 限制缓存大小
        if len(self._price_cache) > 200:
            oldest_symbol = min(self._price_cache.items(), key=lambda x: x[1][1])[0]
            del self._price_cache[oldest_symbol]
