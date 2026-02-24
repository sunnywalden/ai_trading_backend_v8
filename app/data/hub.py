"""V10: DataHub — 多数据源路由层

优先级: DATA_HUB_PRIMARY → 失败时自动切换 DATA_HUB_FALLBACK
支持源: yfinance (历史+延迟), tiger (实时报价)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from app.core.config import settings

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
        from app.broker.factory import get_option_client  # 复用 broker factory

        client = get_option_client()
        # 若是 DummyClient，抛出异常让 fallback 处理
        from app.broker.dummy_option_client import DummyOptionClient

        if isinstance(client, DummyOptionClient):
            raise RuntimeError("Tiger real client not configured, skipping")

        # Tiger SDK 调用（使用 tigeropen quote client）
        raise NotImplementedError("Tiger OHLCV integration pending Tiger SDK setup")

    async def _tiger_quote(self, symbol: str) -> dict:
        raise NotImplementedError("Tiger real-time quote integration pending")


# 全局单例
data_hub = DataHub()
