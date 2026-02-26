"""V10: DataHub — 多数据源路由层

优先级: DATA_HUB_PRIMARY → 失败时自动切换 DATA_HUB_FALLBACK
支持源: yfinance (历史+延迟), tiger (实时报价)
"""
from __future__ import annotations

import asyncio
import logging
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

        # 港股始终通过 Tiger API 获取，不走 yfinance fallback
        if is_hk_stock(symbol):
            normalized = normalize_hk_symbol(symbol)
            logger.debug(f"DataHub: HK symbol detected ({symbol} -> {normalized}), force Tiger")
            return await self._tiger_ohlcv(normalized, start, end, interval)

        try:
            return await self._fetch_ohlcv(primary, symbol, start, end, interval)
        except Exception as e:
            logger.warning(f"DataHub primary={primary} failed for {symbol}: {e}, trying {fallback}")
            try:
                return await self._fetch_ohlcv(fallback, symbol, start, end, interval)
            except Exception as e2:
                logger.error(f"DataHub fallback={fallback} also failed for {symbol}: {e2}")
                raise

    async def get_quote(self, symbol: str) -> dict:
        """获取实时/延迟报价"""
        primary = settings.DATA_HUB_PRIMARY
        fallback = settings.DATA_HUB_FALLBACK

        # 港股始终通过 Tiger API 获取实时报价
        if is_hk_stock(symbol):
            normalized = normalize_hk_symbol(symbol)
            logger.debug(f"DataHub quote: HK symbol ({symbol} -> {normalized}), force Tiger")
            return await self._tiger_quote(normalized)

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
            logger.error(f"Tiger _tiger_quote error for {symbol}: {e}")
            raise


# 全局单例
data_hub = DataHub()
