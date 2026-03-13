"""V10: DataHub — 多数据源路由层

优先级: DATA_HUB_PRIMARY → 失败时自动切换 DATA_HUB_FALLBACK
支持源: yfinance (历史+延迟), tiger (实时报价)
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, timedelta, datetime
from typing import Optional

import pandas as pd

from app.core.config import settings
from app.broker.factory import make_option_broker_client, is_hk_stock, normalize_hk_symbol
from app.broker.tiger_option_client import TigerOptionClient
from app.broker.dummy_option_client import DummyOptionClient
try:
    from tigeropen.common.consts import BarPeriod
except ImportError:
    BarPeriod = None

logger = logging.getLogger(__name__)


class DataHub:
    """统一数据访问接口，屏蔽底层数据源差异"""

    def __init__(self) -> None:
        # Tiger 账户若未开通港股行情权限，港股请求会稳定返回 permission denied。
        # 记录该状态后，后续港股请求直接走 yfinance，避免重复错误日志和无意义重试。
        self._hk_tiger_permission_denied = False
        self._tiger_ohlcv_cooldown_until = 0.0
        self._tiger_ohlcv_cooldown_reason = ""
        self._tiger_ohlcv_cooldown_started_at: datetime | None = None
        self._tiger_ohlcv_last_error_at: datetime | None = None
        self._tiger_ohlcv_last_recovered_at: datetime | None = None
        self._tiger_ohlcv_last_error_message: str | None = None
        self._tiger_ohlcv_last_symbol: str | None = None
        self._tiger_ohlcv_denied_symbols: dict[str, float] = {}
        self._tiger_ohlcv_occupied_symbols: set[str] = set()
        self._tiger_ohlcv_occupied_updated_at: float = 0.0
        self._tiger_ohlcv_permission_pattern = re.compile(r"occupied symbols:\s*\[(.*?)\]", re.IGNORECASE | re.DOTALL)

    @staticmethod
    def _is_tiger_hk_permission_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "permission denied" in msg and "hk market" in msg

    @staticmethod
    def _is_tiger_ohlcv_rate_limit_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "rate limit error" in msg and "kline" in msg

    @staticmethod
    def _is_tiger_ohlcv_permission_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "permission denied" in msg and "hk market" not in msg

    def _is_tiger_ohlcv_cooling_down(self) -> bool:
        return time.monotonic() < self._tiger_ohlcv_cooldown_until

    def _set_tiger_ohlcv_cooldown(self, seconds: int, reason: str) -> None:
        self._tiger_ohlcv_cooldown_until = time.monotonic() + max(seconds, 0)
        self._tiger_ohlcv_cooldown_reason = reason
        now = datetime.now()
        self._tiger_ohlcv_cooldown_started_at = now
        self._tiger_ohlcv_last_error_at = now
        self._tiger_ohlcv_last_recovered_at = None

    def _resolve_ohlcv_source(
        self,
        requested_source: str,
        alternate_source: str | None = None,
    ) -> str | None:
        if requested_source != "tiger":
            return requested_source

        if not self._is_tiger_ohlcv_cooling_down():
            return requested_source

        if alternate_source and alternate_source != "tiger":
            return alternate_source

        return None

    def _record_tiger_ohlcv_failure(self, exc: Exception, symbol: str) -> None:
        self._tiger_ohlcv_last_error_message = str(exc)
        self._tiger_ohlcv_last_symbol = symbol
        if self._is_tiger_ohlcv_rate_limit_error(exc):
            self._set_tiger_ohlcv_cooldown(
                settings.DATA_HUB_TIGER_OHLCV_RATE_LIMIT_COOLDOWN_SECONDS,
                "rate-limit",
            )
            logger.warning(
                "DataHub: Tiger OHLCV rate-limited for %s, cooling down %ss and preferring yfinance",
                symbol,
                settings.DATA_HUB_TIGER_OHLCV_RATE_LIMIT_COOLDOWN_SECONDS,
            )
        elif self._is_tiger_ohlcv_permission_error(exc):
            now = time.monotonic()
            normalized = normalize_hk_symbol(symbol) if is_hk_stock(symbol) else str(symbol).strip().upper()
            self._tiger_ohlcv_denied_symbols[normalized] = now
            occupied = self._parse_tiger_ohlcv_occupied_symbols(str(exc))
            if occupied:
                self._tiger_ohlcv_occupied_symbols = occupied
                self._tiger_ohlcv_occupied_updated_at = now
                if normalized in occupied:
                    self._tiger_ohlcv_denied_symbols.pop(normalized, None)
            logger.warning(
                "DataHub: Tiger OHLCV permission denied for %s, preferring yfinance and caching occupied-symbol budget",
                symbol,
            )

    def _parse_tiger_ohlcv_occupied_symbols(self, message: str) -> set[str]:
        match = self._tiger_ohlcv_permission_pattern.search(message or "")
        if not match:
            return set()
        parsed: set[str] = set()
        for token in match.group(1).split(","):
            cleaned = token.strip().strip("'\"")
            if not cleaned:
                continue
            parsed.add(normalize_hk_symbol(cleaned) if is_hk_stock(cleaned) else cleaned.upper())
        return parsed

    def _should_attempt_tiger_ohlcv_for_symbol(self, symbol: str) -> bool:
        normalized = normalize_hk_symbol(symbol) if is_hk_stock(symbol) else str(symbol).strip().upper()
        now = time.monotonic()
        denied_at = self._tiger_ohlcv_denied_symbols.get(normalized)
        ttl = settings.DATA_HUB_TIGER_OHLCV_PERMISSION_COOLDOWN_SECONDS
        if denied_at is not None:
            if now - denied_at < ttl:
                return False
            self._tiger_ohlcv_denied_symbols.pop(normalized, None)

        if self._tiger_ohlcv_occupied_symbols and now - self._tiger_ohlcv_occupied_updated_at < ttl:
            return normalized in self._tiger_ohlcv_occupied_symbols
        return True

    def get_tiger_ohlcv_runtime_status(self) -> dict[str, object]:
        now = datetime.now()
        remaining_seconds = max(0, int(round(self._tiger_ohlcv_cooldown_until - time.monotonic())))
        cooling_down = remaining_seconds > 0

        if not cooling_down and self._tiger_ohlcv_cooldown_reason and self._tiger_ohlcv_last_recovered_at is None:
            self._tiger_ohlcv_last_recovered_at = now

        if cooling_down:
            message = (
                f"Tiger OHLCV cooling down: reason={self._tiger_ohlcv_cooldown_reason or 'cooldown'}"
                f" · remaining={remaining_seconds}s"
                + (f" · symbol={self._tiger_ohlcv_last_symbol}" if self._tiger_ohlcv_last_symbol else "")
            )
        elif self._tiger_ohlcv_last_recovered_at is not None:
            message = "Tiger OHLCV cooldown recovered; primary path is available again"
        else:
            message = "Tiger OHLCV path is healthy"

        return {
            "cooling_down": cooling_down,
            "reason": self._tiger_ohlcv_cooldown_reason or None,
            "remaining_seconds": remaining_seconds,
            "started_at": self._tiger_ohlcv_cooldown_started_at,
            "last_error_at": self._tiger_ohlcv_last_error_at,
            "last_recovered_at": self._tiger_ohlcv_last_recovered_at,
            "last_error_message": self._tiger_ohlcv_last_error_message,
            "last_symbol": self._tiger_ohlcv_last_symbol,
            "message": message,
        }

    @staticmethod
    def _normalize_hk_symbols(symbol: str) -> tuple[str, str]:
        normalized_tiger = normalize_hk_symbol(symbol)
        core = normalized_tiger.lstrip('0') or '0'
        normalized_yf = f"{core.zfill(4)}.HK"
        return normalized_tiger, normalized_yf

    async def get_ohlcv(
        self,
        symbol: str,
        start: date,
        end: Optional[date] = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        获取 OHLCV 历史数据
        返回列: open, high, low, close, volume (index: date)
        """
        end = end or date.today()
        primary = settings.DATA_HUB_PRIMARY
        fallback = settings.DATA_HUB_FALLBACK

        # 港股处理逻辑
        if is_hk_stock(symbol):
            normalized_tiger, normalized_yf = self._normalize_hk_symbols(symbol)
            
            logger.debug(f"DataHub: HK symbol detected ({symbol}), Tiger: {normalized_tiger}, YF: {normalized_yf}")

            if self._hk_tiger_permission_denied:
                logger.info(
                    f"DataHub: Tiger HK permission unavailable, skip Tiger OHLCV for {normalized_tiger}"
                )
                return await self._fetch_ohlcv("yfinance", normalized_yf, start, end, interval)
            
            # 优先尝试 Tiger API
            try:
                return await self._tiger_ohlcv(normalized_tiger, start, end, interval)
            except Exception as e:
                if self._is_tiger_hk_permission_error(e):
                    self._hk_tiger_permission_denied = True
                    logger.warning(
                        f"DataHub: Tiger HK permission unavailable for {normalized_tiger}, "
                        "switching to yfinance for subsequent HK OHLCV requests"
                    )
                else:
                    logger.warning(f"DataHub: Tiger fail for {normalized_tiger}: {e}, trying yfinance as fallback")
                return await self._fetch_ohlcv("yfinance", normalized_yf, start, end, interval)

        primary_source = self._resolve_ohlcv_source(primary, fallback)
        fallback_source = self._resolve_ohlcv_source(fallback, "yfinance")

        if primary == "tiger" and primary_source != "tiger":
            logger.info(
                "DataHub: Tiger OHLCV cooling down (%s), skip Tiger for %s and use %s",
                self._tiger_ohlcv_cooldown_reason or "cooldown",
                symbol,
                primary_source,
            )

        if primary_source is None:
            raise RuntimeError(
                f"Tiger OHLCV cooling down for {symbol} and no non-Tiger primary source is available"
            )

        try:
            return await self._fetch_ohlcv(primary_source, symbol, start, end, interval)
        except Exception as e:
            if primary_source == "tiger":
                self._record_tiger_ohlcv_failure(e, symbol)

            if fallback_source is None or fallback_source == primary_source:
                logger.error(
                    f"DataHub fallback unavailable after primary={primary_source} failed for {symbol}: {e}"
                )
                raise

            logger.warning(
                f"DataHub primary={primary_source} failed for {symbol}: {e}, trying {fallback_source}"
            )
            try:
                return await self._fetch_ohlcv(fallback_source, symbol, start, end, interval)
            except Exception as e2:
                logger.error(f"DataHub fallback={fallback_source} also failed for {symbol}: {e2}")
                raise

    async def get_quote(self, symbol: str) -> dict:
        """获取实时/延迟报价"""
        primary = settings.DATA_HUB_PRIMARY
        fallback = settings.DATA_HUB_FALLBACK

        # 港股处理
        if is_hk_stock(symbol):
            normalized_tiger, normalized_yf = self._normalize_hk_symbols(symbol)

            if self._hk_tiger_permission_denied:
                logger.info(
                    f"DataHub: Tiger HK permission unavailable, skip Tiger quote for {normalized_tiger}"
                )
                return await self._fetch_quote("yfinance", normalized_yf)
            
            try:
                return await self._tiger_quote(normalized_tiger)
            except Exception as e:
                if self._is_tiger_hk_permission_error(e):
                    self._hk_tiger_permission_denied = True
                    logger.warning(
                        f"DataHub: Tiger HK permission unavailable for {normalized_tiger}, "
                        "switching to yfinance for subsequent HK quote requests"
                    )
                else:
                    logger.warning(f"DataHub: Tiger quote fail for {normalized_tiger}: {e}, trying yfinance")
                return await self._fetch_quote("yfinance", normalized_yf)

        try:
            return await self._fetch_quote(primary, symbol)
        except Exception as e:
            logger.warning(f"DataHub quote primary={primary} failed: {e}")
            return await self._fetch_quote(fallback, symbol)

    # ──────────────────────────────────────────
    # 内部适配器
    # ──────────────────────────────────────────

    async def _fetch_ohlcv(
        self, source: str, symbol: str, start: date, end: date, interval: str
    ) -> pd.DataFrame:
        if source == "yfinance":
            return await asyncio.to_thread(
                self._yf_ohlcv, symbol, start, end, interval
            )
        elif source == "tiger":
            if not self._should_attempt_tiger_ohlcv_for_symbol(symbol):
                raise RuntimeError(f"Tiger OHLCV budget skip for {symbol}: symbol not in occupied historical set")
            return await self._tiger_ohlcv(symbol, start, end, interval)
        else:
            raise ValueError(f"Unknown data source: {source}")

    async def _fetch_quote(self, source: str, symbol: str) -> dict:
        if source == "yfinance":
            return await asyncio.to_thread(self._yf_quote, symbol)
        elif source == "tiger":
            return await self._tiger_quote(symbol)
        else:
            raise ValueError(f"Unknown data source: {source}")

    # ── yfinance ──

    def _yf_ohlcv(self, symbol: str, start: date, end: date, interval: str) -> pd.DataFrame:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval=interval,
            auto_adjust=True,
        )
        if df.empty:
            raise ValueError(f"yfinance returned empty data for {symbol}")
        df.index = pd.to_datetime(df.index).date
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]]

    def _yf_quote(self, symbol: str) -> dict:
        import yfinance as yf

        info = yf.Ticker(symbol).fast_info
        return {
            "symbol": symbol,
            "price": getattr(info, "last_price", None),
            "open": getattr(info, "open", None),
            "high": getattr(info, "day_high", None),
            "low": getattr(info, "day_low", None),
            "volume": getattr(info, "three_month_average_volume", None),
            "source": "yfinance",
        }

    # ── Tiger ──

    async def _tiger_ohlcv(
        self, symbol: str, start: date, end: date, interval: str
    ) -> pd.DataFrame:
        """Tiger API OHLCV — 需要有效 Tiger 账户配置"""
        client = make_option_broker_client()

        if isinstance(client, DummyOptionClient) or not isinstance(client, TigerOptionClient):
            raise RuntimeError("Tiger real client not configured, skipping")

        if BarPeriod is None:
            raise RuntimeError("Tiger SDK not installed")

        # 映射 interval 到 Tiger BarPeriod
        mapping = {
            "1m": BarPeriod.ONE_MINUTE,
            "3m": BarPeriod.THREE_MINUTES,
            "5m": BarPeriod.FIVE_MINUTES,
            "15m": BarPeriod.FIFTEEN_MINUTES,
            "30m": BarPeriod.HALF_HOUR,
            "1h": BarPeriod.ONE_HOUR,
            "2h": BarPeriod.TWO_HOURS,
            "4h": BarPeriod.FOUR_HOURS,
            "1d": BarPeriod.DAY,
            "1w": BarPeriod.WEEK,
            "1mo": BarPeriod.MONTH,
        }
        period = mapping.get(interval, BarPeriod.DAY)

        # 转换时间范围
        begin_ms = int(datetime.combine(start, datetime.min.time()).timestamp() * 1000)
        # End date + 1 day to ensure inclusion
        end_ms = int(datetime.combine(end + timedelta(days=1), datetime.min.time()).timestamp() * 1000)

        try:
            # Tiger SDK 调用 (在线程池中运行)
            bars_df = await client._run_in_executor(
                client.quote_client.get_bars,
                [symbol],
                period=period,
                begin_time=begin_ms,
                end_time=end_ms
            )

            if bars_df is None or bars_df.empty:
                raise ValueError(f"Tiger returned empty data for {symbol}")

            df = bars_df.copy()
            # 统一列名以匹配 get_ohlcv 的返回要求
            df.columns = [c.lower() for c in df.columns]

            if "time" in df.columns:
                df.index = pd.to_datetime(df["time"], unit="ms").dt.date
                df.drop(columns=["time"], inplace=True)
            
            # 如果是多 symbol 返回，过滤当前 symbol
            if "symbol" in df.columns:
                df = df[df["symbol"] == symbol.upper()].drop(columns=["symbol"], errors="ignore")

            # 只保留需要的列并按日期排序
            needed = ["open", "high", "low", "close", "volume"]
            df = df[[c for c in needed if c in df.columns]]
            df.sort_index(inplace=True)
            return df
        except Exception as e:
            if self._is_tiger_hk_permission_error(e):
                logger.warning(f"Tiger _tiger_ohlcv permission denied for {symbol}: {e}")
            else:
                logger.error(f"Tiger _tiger_ohlcv error for {symbol}: {e}")
            raise

    async def _tiger_quote(self, symbol: str) -> dict:
        client = make_option_broker_client()
        if not isinstance(client, TigerOptionClient):
            raise RuntimeError("Tiger client not configured")

        try:
            df = await client._run_in_executor(
                client.quote_client.get_stock_briefs,
                [symbol]
            )
            if df is None or df.empty:
                 raise ValueError(f"Tiger quote empty for {symbol}")
            
            # 统一列名为小写
            df.columns = [c.lower() for c in df.columns]
            row = df.iloc[0]
            
            return {
                "symbol": symbol,
                "price": float(row.get("latest_price") or row.get("latestprice") or row.get("price") or 0.0),
                "open": float(row.get("open") or 0.0),
                "high": float(row.get("high") or row.get("day_high") or 0.0),
                "low": float(row.get("low") or row.get("day_low") or 0.0),
                "volume": int(row.get("volume") or 0),
                "source": "tiger",
            }
        except Exception as e:
            if self._is_tiger_hk_permission_error(e):
                logger.warning(f"Tiger _tiger_quote permission denied for {symbol}: {e}")
            else:
                logger.error(f"Tiger _tiger_quote error for {symbol}: {e}")
            raise


# 全局单例
data_hub = DataHub()
