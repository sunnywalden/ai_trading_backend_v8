"""V10: OptionsAnalysisService — 期权数据分析（只读，不执行交易）"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OptionsAnalysisService:
    """
    期权分析工具（只读）：
    - IV 曲面 / IV Rank / P/C Ratio
    - 异常大单检测
    - Greeks 汇总（通过 yfinance options）
    注意：ALLOWED_ASSET_TYPES=STOCK 时，此服务仍可提供只读分析（不实际下单）
    """

    async def get_iv_surface(self, symbol: str) -> dict:
        """获取 IV 曲面数据（到期日 × 行权价 → IV）"""
        return await asyncio.to_thread(self._fetch_iv_surface, symbol)

    async def get_iv_rank(self, symbol: str, lookback_days: int = 252) -> dict:
        """计算 IV Rank（当前 IV 在过去 252 天区间中的百分位）"""
        return await asyncio.to_thread(self._calc_iv_rank, symbol, lookback_days)

    async def get_unusual_activity(self, symbol: str) -> List[dict]:
        """检测异常大单（成交量 > 10× 未平仓量）"""
        return await asyncio.to_thread(self._detect_unusual, symbol)

    async def get_summary(self, symbol: str) -> dict:
        """综合摘要：IV Rank + Put/Call Ratio + 最活跃到期日"""
        iv_rank = await self.get_iv_rank(symbol)
        unusual = await self.get_unusual_activity(symbol)
        surface = await self.get_iv_surface(symbol)

        # Put/Call Ratio（近月）
        pc_ratio = self._calc_pc_ratio(surface.get("chain", {}))

        return {
            "symbol": symbol,
            "iv_rank": iv_rank.get("iv_rank"),
            "current_iv": iv_rank.get("current_iv"),
            "iv_52w_high": iv_rank.get("iv_52w_high"),
            "iv_52w_low": iv_rank.get("iv_52w_low"),
            "put_call_ratio": pc_ratio,
            "unusual_activity_count": len(unusual),
            "unusual_activity": unusual[:5],
            "surface": surface.get("surface_data", []),
            "note": "只读分析，不支持期权交易",
        }

    # ──────────────────────────────────────────
    # 内部实现（使用 yfinance）
    # ──────────────────────────────────────────

    def _fetch_iv_surface(self, symbol: str) -> dict:
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            expirations = ticker.options
            if not expirations:
                return {"symbol": symbol, "surface_data": [], "chain": {}}

            surface_data = []
            chain_data = {}
            for exp in expirations[:4]:  # 最多分析 4 个到期日
                try:
                    chain = ticker.option_chain(exp)
                    calls = chain.calls[["strike", "impliedVolatility", "volume", "openInterest"]].to_dict("records")
                    puts = chain.puts[["strike", "impliedVolatility", "volume", "openInterest"]].to_dict("records")
                    for c in calls:
                        surface_data.append({
                            "expiration": exp,
                            "strike": c.get("strike"),
                            "type": "call",
                            "iv": round(float(c.get("impliedVolatility", 0)), 4),
                        })
                    chain_data[exp] = {"calls": calls, "puts": puts}
                except Exception as e:
                    logger.warning(f"Failed to fetch option chain for {symbol} {exp}: {e}")

            return {"symbol": symbol, "surface_data": surface_data, "chain": chain_data}
        except ImportError:
            return {"symbol": symbol, "surface_data": [], "error": "yfinance not available"}
        except Exception as e:
            logger.error(f"IV surface error for {symbol}: {e}")
            return {"symbol": symbol, "surface_data": [], "error": str(e)}

    def _calc_iv_rank(self, symbol: str, lookback_days: int = 252) -> dict:
        try:
            import yfinance as yf
            import numpy as np

            ticker = yf.Ticker(symbol)
            end = date.today()
            start = end - timedelta(days=lookback_days)
            hist = ticker.history(start=start.isoformat(), end=end.isoformat())

            if hist.empty:
                return {"symbol": symbol, "iv_rank": None}

            # 用历史波动率代理 IV（HV）
            returns = hist["Close"].pct_change().dropna()
            hv_series = returns.rolling(21).std() * (252 ** 0.5)
            hv_series = hv_series.dropna()
            if hv_series.empty:
                return {"symbol": symbol, "iv_rank": None}

            current_hv = float(hv_series.iloc[-1])
            hv_52w_high = float(hv_series.max())
            hv_52w_low = float(hv_series.min())

            iv_rank = (current_hv - hv_52w_low) / (hv_52w_high - hv_52w_low) * 100 if hv_52w_high != hv_52w_low else 50.0

            return {
                "symbol": symbol,
                "current_iv": round(current_hv, 4),
                "iv_52w_high": round(hv_52w_high, 4),
                "iv_52w_low": round(hv_52w_low, 4),
                "iv_rank": round(iv_rank, 1),
                "note": "使用历史波动率(HV)代理IV",
            }
        except Exception as e:
            logger.error(f"IV rank error for {symbol}: {e}")
            return {"symbol": symbol, "iv_rank": None, "error": str(e)}

    def _detect_unusual(self, symbol: str) -> List[dict]:
        """检测异常大单"""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            expirations = ticker.options
            if not expirations:
                return []

            unusual = []
            for exp in expirations[:2]:
                try:
                    chain = ticker.option_chain(exp)
                    for df, opt_type in [(chain.calls, "call"), (chain.puts, "put")]:
                        for _, row in df.iterrows():
                            vol = float(row.get("volume", 0) or 0)
                            oi = float(row.get("openInterest", 0) or 0)
                            if oi > 0 and vol > oi * 10:
                                unusual.append({
                                    "symbol": symbol,
                                    "expiration": exp,
                                    "strike": row.get("strike"),
                                    "type": opt_type,
                                    "volume": int(vol),
                                    "open_interest": int(oi),
                                    "ratio": round(vol / oi, 1),
                                })
                except Exception:
                    pass

            return sorted(unusual, key=lambda x: x["ratio"], reverse=True)
        except Exception as e:
            return []

    def _calc_pc_ratio(self, chain: dict) -> Optional[float]:
        """计算 Put/Call Volume Ratio"""
        try:
            total_call_vol = 0
            total_put_vol = 0
            for exp, data in chain.items():
                total_call_vol += sum(r.get("volume", 0) or 0 for r in data.get("calls", []))
                total_put_vol += sum(r.get("volume", 0) or 0 for r in data.get("puts", []))
            return round(total_put_vol / total_call_vol, 2) if total_call_vol > 0 else None
        except Exception:
            return None


# 全局单例
options_analysis_service = OptionsAnalysisService()
