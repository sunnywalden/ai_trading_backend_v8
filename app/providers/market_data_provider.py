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
import threading
from concurrent.futures import ThreadPoolExecutor


class MarketDataProvider:
    """市场数据提供者
    
    Tiger QuoteClient 为类变量单例：无论创建多少个 MarketDataProvider 实例，
    都只会初始化一次 QuoteClient（只触发一次 query_license），从而避免
    Tiger 对 user_license 接口 10次/分钟 的限流。
    """
    
    # ── 类级别单例 Tiger 客户端（所有实例共享，只初始化一次）──
    _shared_tiger_client = None
    _tiger_client_init_lock = threading.Lock()
    _shared_executor = ThreadPoolExecutor(max_workers=4)
    # ── 类级别共享价格缓存（所有实例共享，避免重复请求）──
    _class_price_cache: Dict[str, tuple] = {}
    # ── 负面缓存：记录无效或不存在的 symbol 避免重复请求 ──
    _invalid_symbol_cache: Dict[str, float] = {}
    
    def __init__(self):
        self.cache_duration = 300
        self.primary_source = settings.DATA_HUB_PRIMARY or "tiger"
        self.fallback_source = settings.DATA_HUB_FALLBACK or "yfinance"

        # 实例复用类级别的 Tiger 客户端（懒初始化）
        if MarketDataProvider._shared_tiger_client is None:
            MarketDataProvider._maybe_init_tiger_client()
        self._tiger_quote_client = MarketDataProvider._shared_tiger_client

        self._executor = MarketDataProvider._shared_executor
        self._ext_api_semaphore = asyncio.Semaphore(settings.EXTERNAL_API_CONCURRENCY)
        
        # K线数据缓存: {(symbol, period, interval): (data, timestamp)}
        self._bars_cache: Dict[tuple, tuple] = {}
        self._bars_cache_ttl = 1800  # K线缓存30分钟（历史数据变动慢）
        
        # 价格数据缓存：指向类级别共享字典（所有实例共享同一份缓存）
        self._price_cache = MarketDataProvider._class_price_cache
        self._price_cache_ttl = 300  # 价格缓存5分钟（减少 Tiger API 调用频率）
        
        # Symbol信息缓存 (包含 lot_size)
        self._symbol_info_cache: Dict[str, tuple] = {}
        self._symbol_info_ttl = 3600 * 24  # 缓存1天
        
        # 请求频率控制: 记录每个symbol的最后请求时间
        self._last_request_time: Dict[str, float] = {}
        self._request_min_interval = 1.0  # 每个symbol最少间隔1秒

    @classmethod
    def _maybe_init_tiger_client(cls) -> None:
        """线程安全地初始化单例 Tiger QuoteClient（只执行一次）"""
        with cls._tiger_client_init_lock:
            if cls._shared_tiger_client is not None:
                return  # 双重检查
            if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID and get_client_config and QuoteClient:
                try:
                    client_config = get_client_config(
                        private_key_path=settings.TIGER_PRIVATE_KEY_PATH,
                        tiger_id=settings.TIGER_ID,
                        account=settings.TIGER_ACCOUNT,
                    )
                    cls._shared_tiger_client = QuoteClient(client_config)
                    print("[MarketData] Tiger QuoteClient initialized (singleton)")
                except Exception as e:
                    print(f"[MarketData] Tiger QuoteClient init failed: {e}")
                    cls._shared_tiger_client = None

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
        yahoo_symbol = self._to_yahoo_symbol(symbol)
        return yf.Ticker(yahoo_symbol)
    
    def _to_yahoo_symbol(self, symbol: str) -> str:
        """将任意符号转换为 Yahoo Finance 格式
        
        Args:
            symbol: 符号，如 0700, 700.HK, AAPL, ^HSI, HSI 等
        """
        s = symbol.strip().upper()
        # 港股处理
        if s.endswith(".HK"):
            return s
        if s.isdigit():
            return f"{str(int(s)).zfill(4)}.HK" # e.g. 700 -> 0700.HK
        
        # 指数处理 (Tiger 指数通常以 . 开头)
        index_map = {
            "HSI": "^HSI",
            "DJI": "^DJI",
            "IXIC": "^IXIC",
            "SPX": "^GSPC",
        }
        if s in index_map:
            return index_map[s]
        if s.startswith("."): # Tiger format like .DJI
            return f"^{s[1:]}"
            
        return s

    def _to_tiger_symbol(self, symbol: str) -> str:
        """将任意符号转换为 Tiger 格式"""
        s = symbol.strip().upper()
        if ".HK" in s:
            # 移除 .HK 后缀并根据需要补零
            num_part = s.split(".")[0]
            if num_part.isdigit():
                return num_part.zfill(5)
            return num_part
        if s.isdigit() and len(s) < 5:
            return s.zfill(5)
        if s.startswith("^"):
            return f".{s[1:]}"
        return s

    def _is_invalid(self, symbol: str) -> bool:
        """检查 symbol 是否在负面缓存中且未过期 (1小时)"""
        if symbol in MarketDataProvider._invalid_symbol_cache:
            ts = MarketDataProvider._invalid_symbol_cache[symbol]
            if time.time() - ts < 3600:
                return True
            else:
                del MarketDataProvider._invalid_symbol_cache[symbol]
        return False

    def _mark_invalid(self, symbol: str):
        """标记 symbol 为无效"""
        MarketDataProvider._invalid_symbol_cache[symbol] = time.time()
        # LRU 限制
        if len(MarketDataProvider._invalid_symbol_cache) > 200:
            oldest = min(MarketDataProvider._invalid_symbol_cache.items(), key=lambda x: x[1])[0]
            del MarketDataProvider._invalid_symbol_cache[oldest]
    
    async def get_historical_data(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d"
    ) -> pd.DataFrame:
        """获取历史数据 - 考虑优先级策略和负面缓存
        
        Args:
            symbol: 股票代码
            period: 时间周期 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: 时间间隔 (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
        """
        if self._is_invalid(symbol):
            return pd.DataFrame()

        # 1. 检查缓存
        cache_key = (symbol, period, interval)
        cached_data = self._get_cached_bars(cache_key)
        if cached_data is not None:
            return cached_data
        
        # 2. 依次尝试数据源
        primary = self.primary_source
        fallback = self.fallback_source
        
        sources = [primary, fallback]
        if primary == fallback:
            sources = [primary]

        for source in sources:
            if source == "tiger":
                # Tiger 仅支持 1d 日线且有客户端
                if self._tiger_quote_client and interval.lower() in ("1d", "day") and BarPeriod is not None:
                    try:
                        await self._wait_for_rate_limit(symbol)
                        df = await self._get_tiger_bars(symbol, period)
                        if df is not None and len(df) > 0:
                            self._cache_bars(cache_key, df)
                            return df
                    except Exception as e:
                        print(f"[MarketData] Tiger API failed for {symbol}: {e}")
            elif source == "yfinance":
                df = await self._get_yahoo_data_with_retry(symbol, period, interval)
                if df is not None and len(df) > 0:
                    self._cache_bars(cache_key, df, ttl=3600)  # Yahoo 数据通常变动更慢，可多缓存一会
                    return df
        
        # 最终失败
        print(f"[MarketData] All data sources failed for {symbol}")
        # 短时间内不再请求该无效/缺失 symbol
        self._mark_invalid(symbol)
        return pd.DataFrame()
    
    async def get_current_price(self, symbol: str) -> float:
        """获取当前价格 - 考虑优先级策略和负面缓存"""
        if self._is_invalid(symbol):
            return 0.0
            
        # 1. 内存/Redis 缓存命中（已在 get_prices_batch 中做了更精细的处理，
        # 但单次请求也要对内存缓存进行复查）
        cached_price = self._get_cached_price(symbol)
        if cached_price is not None:
            return cached_price
        
        # 2. 依次尝试数据源
        primary = self.primary_source
        fallback = self.fallback_source
        
        sources = [primary, fallback]
        # 如果 primary == fallback, 只有一个 source
        if primary == fallback:
            sources = [primary]

        for source in sources:
            if source == "tiger" and self._tiger_quote_client:
                price = await self._get_tiger_price_single(symbol)
                if price > 0:
                    return price
            elif source == "yfinance":
                price = await self._get_yahoo_price_robust(symbol)
                if price > 0:
                    self._cache_price(symbol, price)
                    return price
                    
        # 3. 最终失败，标记为无效（短期内不再请求）
        print(f"[MarketData] All sources failed for price of {symbol}")
        self._mark_invalid(symbol)
        return 0.0

    async def _get_tiger_price_single(self, symbol: str) -> float:
        """获取单个 Tiger 价格调用"""
        if not self._tiger_quote_client:
            return 0.0
        tiger_sym = self._to_tiger_symbol(symbol)
        try:
            await self._wait_for_rate_limit(tiger_sym)
            df = await self._run_external(self._tiger_quote_client.get_stock_briefs, [tiger_sym])
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                for key in ("latest_price", "latestPrice", "close", "pre_close"):
                    if key in row and row[key] is not None:
                        price = float(row[key])
                        self._cache_price(symbol, price)
                        return price
        except Exception as e:
            print(f"[MarketData] Tiger API single price failed for {symbol} ({tiger_sym}): {e}")
        return 0.0

    async def _get_yahoo_price_robust(self, symbol: str) -> float:
        """获取单个 Yahoo 价格（使用 history 替代 info 减少失败）"""
        try:
            gate = await api_monitor.can_call_provider(APIProvider.YAHOO_FINANCE)
            if not gate.get("can_call", True):
                return 0.0
            
            ticker = self.get_ticker(symbol)
            # 使用 1d 历史数据获取最后收盘价/现价，这比 .info 稳定得多
            df = await self._run_external(ticker.history, period="1d")
            if df is not None and not df.empty:
                price = float(df.iloc[-1]["Close"])
                return price
            
            # info 兜底（现在很多时候会返回 empty 或者报错）
            info = ticker.info
            price = info.get('currentPrice') or info.get('regularMarketPrice', 0.0)
            return float(price)
        except Exception:
            return 0.0
    
    async def get_quote(self, symbol: str) -> Dict:
        """获取实时报价 - 增加容错"""
        if self._is_invalid(symbol):
            return {"symbol": symbol, "error": "Invalid symbol"}

        if self._tiger_quote_client:
            try:
                tiger_sym = self._to_tiger_symbol(symbol)
                df = await self._run_external(self._tiger_quote_client.get_stock_briefs, [tiger_sym])
                if df is not None and len(df) > 0:
                    row = df.iloc[0]
                    return {
                        "symbol": symbol,
                        "current_price": float(row.get("latest_price") or row.get("latestPrice") or row.get("close") or 0.0),
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

        try:
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
        except Exception:
            return {'symbol': symbol, 'current_price': 0.0, 'source': 'error'}
    
    async def get_company_info(self, symbol: str) -> Dict:
        """获取公司基本信息 - 增加容错"""
        try:
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
        except Exception:
            return {'symbol': symbol, 'name': 'Unknown'}
    
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
        rec = ticker.recommendations
        if isinstance(rec, pd.DataFrame):
            return rec
        return pd.DataFrame()
    
    async def get_institutional_holders(self, symbol: str) -> pd.DataFrame:
        """获取机构持仓"""
        ticker = self.get_ticker(symbol)
        holders = ticker.institutional_holders
        if isinstance(holders, pd.DataFrame):
            return holders
        return pd.DataFrame()
    
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
    
    async def batch_get_quotes(self, symbols: List[str]) -> Dict[str, Optional[Dict]]:
        """批量获取报价 — 一次 Tiger API 调用取多个 symbol，减少连接和限流消耗"""
        if not symbols:
            return {}

        # 1. 过滤掉负面缓存中的 symbol
        valid_symbols = [s for s in symbols if not self._is_invalid(s)]
        if not valid_symbols:
            return {s: None for s in symbols}

        # 2. 依次尝试数据源
        primary = self.primary_source
        
        # 如果优先 Tiger
        if primary == "tiger" and self._tiger_quote_client:
            try:
                # 转换符号
                tiger_to_orig = {self._to_tiger_symbol(s): s for s in valid_symbols}
                tiger_syms = list(tiger_to_orig.keys())
                
                df = await self._run_external(self._tiger_quote_client.get_stock_briefs, tiger_syms)
                if df is not None and len(df) > 0:
                    result: Dict[str, Optional[Dict]] = {}
                    for _, row in df.iterrows():
                        t_sym = str(row.get("symbol", ""))
                        orig_sym = tiger_to_orig.get(t_sym)
                        if not orig_sym:
                            continue
                            
                        price = float(row.get("latest_price") or row.get("latestPrice") or row.get("close") or 0.0)
                        if price > 0:
                            self._cache_price(orig_sym, price)
                            
                        result[orig_sym] = {
                            "symbol": orig_sym,
                            "current_price": price,
                            "previous_close": float(row.get("pre_close") or row.get("preClose") or 0.0),
                            "open": float(row.get("open") or 0.0),
                            "day_high": float(row.get("high") or row.get("day_high") or 0.0),
                            "day_low": float(row.get("low") or row.get("day_low") or 0.0),
                            "volume": int(row.get("volume") or 0),
                            "timestamp": datetime.now(),
                            "source": "tiger",
                        }
                    
                    # 补充缺失的
                    for s in symbols:
                        if s not in result:
                            if s in valid_symbols:
                                result[s] = await self.get_quote(s)
                            else:
                                result[s] = None
                    return result
            except Exception as e:
                print(f"[MarketData] Batch Tiger briefs failed: {e}")

        # 全量降级：逐个查询
        quotes: Dict[str, Optional[Dict]] = {}
        for symbol in symbols:
            try:
                quotes[symbol] = await self.get_quote(symbol)
            except Exception:
                quotes[symbol] = None
        return quotes

    async def get_prices_batch(self, symbols: List[str]) -> Dict[str, float]:
        """批量获取多个 symbol 的最新价格。
        
        优先从 Redis/内存缓存读取；对缓存缺失的 symbol 使用 Tiger 批量接口一次
        请求获取，避免每个 symbol 单独调用造成限流。
        """
        from app.core.cache import cache as redis_cache

        result: Dict[str, float] = {}
        missing: List[str] = []

        # 1. 先命中内存缓存
        for sym in symbols:
            cached = self._get_cached_price(sym)
            if cached is not None:
                result[sym] = cached
            else:
                missing.append(sym)

        if not missing:
            return result

        # 2. 命中 Redis 缓存（跨进程共享）
        still_missing: List[str] = []
        for sym in missing:
            redis_val = await redis_cache.get(f"price:{sym}")
            if redis_val is not None:
                try:
                    price = float(redis_val)
                    result[sym] = price
                    self._cache_price(sym, price)  # 回填内存缓存
                except (ValueError, TypeError):
                    still_missing.append(sym)
            else:
                still_missing.append(sym)

        if not still_missing:
            return result

        # 3. 批量调用 Tiger API（一次调用多个 symbol）
        if self._tiger_quote_client:
            try:
                # 转换符号
                tiger_to_orig = {self._to_tiger_symbol(s): s for s in still_missing}
                tiger_syms = list(tiger_to_orig.keys())
                
                df = await self._run_external(
                    self._tiger_quote_client.get_stock_briefs, tiger_syms
                )
                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        t_sym = str(row.get("symbol", ""))
                        orig_sym = tiger_to_orig.get(t_sym)
                        if not orig_sym:
                            continue
                        price = float(
                            row.get("latest_price") or row.get("latestPrice")
                            or row.get("close") or 0.0
                        )
                        if price > 0:
                            result[orig_sym] = price
                            self._cache_price(orig_sym, price)
                            # 写入 Redis（TTL = price_cache_ttl）
                            try:
                                await redis_cache.set(
                                    f"price:{orig_sym}", str(price),
                                    expire=self._price_cache_ttl, is_json=False
                                )
                            except Exception:
                                pass
                            still_missing = [s for s in still_missing if s != orig_sym]
            except Exception as e:
                print(f"[MarketData] Batch Tiger price failed: {e}")

        # 4. 对仍缺失的 symbol 降级到 Yahoo Finance（逐个，不影响已获取的）
        for sym in still_missing:
            try:
                price = await self.get_current_price(sym)  # Yahoo fallback 在内部处理
                result[sym] = price
            except Exception:
                result[sym] = 0.0

        return result
    
    # ==================== 辅助方法 ====================
    
    async def _get_tiger_bars(self, symbol: str, period: str, bar_period=None) -> Optional[pd.DataFrame]:
        """从Tiger API获取K线数据（带监控）"""
        start_time = time.time()
        success = False
        error_msg = None
        result = None
        
        tiger_sym = self._to_tiger_symbol(symbol)
        
        # 映射 bar_period
        if bar_period is None:
            if BarPeriod is None:
                return None
            bar_period = BarPeriod.DAY
            
        try:
            if self._tiger_quote_client is None:
                return None
                
            end_ms = int(datetime.now().timestamp() * 1000)
            limit = self._period_to_limit(period)
            
            bars_df = await self._run_external(
                self._tiger_quote_client.get_bars,
                [tiger_sym],
                period=bar_period,
                end_time=end_ms,
                limit=limit,
            )
            
            if bars_df is None or len(bars_df) == 0:
                error_msg = "Empty bars returned"
            elif len(bars_df) < 5:
                # 即使行数少也作为 success 处理，除非一行都没有
                # 修复: 只有在完全没有数据时才记为 False, 这里的 5 行规则太激进了
                error_msg = f"Few data: {len(bars_df)} rows"
                # 改为 len(bars_df) > 0 即认为某种程度的 success，不触发 monitor 警告
                result = bars_df
                success = True
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
                    df = df[df["symbol"] == tiger_sym].drop(columns=["symbol"], errors="ignore")
                
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
            endpoint=f"get_bars:{tiger_sym}",
            success=success,
            response_time_ms=response_time,
            error_message=error_msg
        )
        
        return result
    
    async def _get_yahoo_data_with_retry(self, symbol: str, period: str, interval: str, max_retries: int = 1) -> Optional[pd.DataFrame]:
        """从Yahoo Finance获取数据（使用统一转换函数）"""
        # 转换为Yahoo格式
        yahoo_symbol = self._to_yahoo_symbol(symbol)
        
        # 检查负面缓存，避免无效 symbol 浪费额度
        if self._is_invalid(yahoo_symbol):
            return None

        gate = await api_monitor.can_call_provider(APIProvider.YAHOO_FINANCE)
        if not gate.get("can_call", True):
            return None
        
        start_time = time.time()
        success = False
        error_msg = None
        result = None
        
        try:
            ticker = yf.Ticker(yahoo_symbol) if yf else None
            if ticker is None:
                error_msg = "yfinance not available"
            else:
                # 增加延迟重试（可选，但这里目前设为 1 次尝试）
                df = await self._run_external(ticker.history, period=period, interval=interval)
                if df is not None and len(df) > 0:
                    result = df
                    success = True
                else:
                    error_msg = "Empty data"
        except Exception as e:
            error_msg = str(e)
        
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
        """获取内存缓存的价格"""
        if symbol in self._price_cache:
            price, timestamp = self._price_cache[symbol]
            if time.time() - timestamp < self._price_cache_ttl:
                return price
            else:
                del self._price_cache[symbol]
        return None
    
    def _cache_price(self, symbol: str, price: float):
        """缓存价格到内存（类级别共享，跨实例有效）"""
        MarketDataProvider._class_price_cache[symbol] = (price, time.time())
        # 简单LRU: 限制缓存大小
        if len(MarketDataProvider._class_price_cache) > 500:
            oldest_symbol = min(
                MarketDataProvider._class_price_cache.items(), key=lambda x: x[1][1]
            )[0]
            del MarketDataProvider._class_price_cache[oldest_symbol]

    async def get_lot_size(self, symbol: str) -> int:
        """获取合约最小交易单位 (Lot Size)
        
        美股通常为 1；港股通常为 100, 500, 1000 等。
        """
        # 1. 简单启发式
        if not symbol.endswith(".HK") and ".US" not in symbol and not symbol.isupper():
            # 非港股美股格式且不全是大写，优先看后缀
            pass
        
        if symbol.endswith(".US") or (symbol.isupper() and "." not in symbol):
            return 1 # 美股大都支持1股或碎股，这里按最小1股计
            
        # 2. 缓存检查
        if symbol in self._symbol_info_cache:
            info, timestamp = self._symbol_info_cache[symbol]
            if time.time() - timestamp < self._symbol_info_ttl:
                return info.get("lot_size", 1)

        # 3. 如果是港股，必须查 API 获取准确 lot_size
        if symbol.endswith(".HK") or symbol.isdigit():
            if self._tiger_quote_client:
                try:
                    tiger_sym = self._to_tiger_symbol(symbol)
                    await self._wait_for_rate_limit(tiger_sym)
                    # 获取证券基本信息
                    briefs = await self._run_external(
                        self._tiger_quote_client.get_stock_briefs,
                        [tiger_sym]
                    )
                    if briefs is not None and not briefs.empty:
                        # Tiger OpenAPI 返回的 briefs 原则上可能包含 lot_size（取决于版本）
                        if 'lot_size' in briefs.columns:
                            lot_size = int(briefs.iloc[0]['lot_size'])
                        else:
                            # 港股常见默认手数为 100（若 API 未返回则使用保守默认值）
                            lot_size = 100
                        
                        self._symbol_info_cache[symbol] = ({"lot_size": lot_size}, time.time())
                        return lot_size
                except Exception as e:
                    print(f"[MarketDataProvider] Error fetching lot size for {symbol}: {e}")
            
            # 如果查不到，港股给个保守默认值 (大部分是100或500, 但返回1可能会导致下单失败)
            return 100 # 风险提示: 应当由 API 返回，100是常见默认值
            
        return 1 # 默认 1


# ───────────────────────────────────────────────────────────
# 全局单例：所有调用方使用这个实例，确保 Tiger QuoteClient 只初始化一次
# 使用方式： from app.providers.market_data_provider import market_data_provider
# ───────────────────────────────────────────────────────────
market_data_provider = MarketDataProvider()
