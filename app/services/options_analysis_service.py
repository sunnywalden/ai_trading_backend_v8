"""V10: OptionsAnalysisService — 期权数据分析（只读，不执行交易）"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _clean_records(records: List[Dict]) -> List[Dict]:
    for r in records:
        for k, v in r.items():
            # 同时覆盖 Python float 和 numpy.float32/float64
            try:
                f = float(v)
                if math.isnan(f) or math.isinf(f):
                    r[k] = 0.0
                elif type(v).__module__ == "numpy" or (type(v).__module__ or "").startswith("numpy."):
                    # 将 numpy 标量转换为 Python 原生类型以保证 JSON 可序列化
                    r[k] = v.item() if hasattr(v, "item") else f
            except (TypeError, ValueError):
                pass
    return records


def _deep_clean(obj: Any) -> Any:
    """递归清除所有 NaN/Inf，同时将 numpy 标量转换为 Python 原生类型。
    yfinance 返回的 numpy.float32 / numpy.float64 不一定是 Python float 子类，
    必须单独处理，否则会绕过 isinstance(obj, float) 检查导致 json.dumps 报错。
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _deep_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_clean(item) for item in obj]
    # 处理 numpy 标量（float32/float64/int32/int64 等）
    type_name = type(obj).__module__
    if type_name == "numpy" or (type_name or "").startswith("numpy."):
        try:
            f = float(obj)
            if math.isnan(f) or math.isinf(f):
                return None
            # 优先转 int，否则转 float
            if hasattr(obj, "item"):
                return obj.item()  # 返回 Python 原生 int / float
            return f
        except (TypeError, ValueError):
            try:
                return int(obj)
            except (TypeError, ValueError):
                return None
    return obj


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
        """综合摘要：符合前端 OptionsSummary 接口声明"""
        iv_rank = await self.get_iv_rank(symbol)
        unusual = await self.get_unusual_activity(symbol)
        surface = await self.get_iv_surface(symbol)

        # Put/Call Ratio（近月）
        pc_ratio = self._calc_pc_ratio(surface.get("chain", {}))

        result = {
            "symbol": symbol,
            "iv_rank": iv_rank.get("iv_rank"),
            "atm_iv": iv_rank.get("current_iv"),  # 对应前端 atm_iv
            "put_call_ratio": pc_ratio,
            "unusual_count": len(unusual),        # 对应前端 unusual_count
            "top_unusual": unusual[:5],           # 对应前端 top_unusual
            "recommendation": self._generate_recommendation(iv_rank, pc_ratio),
            "generated_at": datetime.now().isoformat(),
            "note": "只读分析，不支持期权交易",
            # 保留旧字段兼容性 (可选)
            "iv_52w_high": iv_rank.get("iv_52w_high"),
            "iv_52w_low": iv_rank.get("iv_52w_low"),
            "surface": surface.get("surface", []),
        }
        return _deep_clean(result)

    def _generate_recommendation(self, iv_rank: dict, pc_ratio: Optional[float]) -> str:
        ir = iv_rank.get("iv_rank", 50)
        if ir > 70:
            return "IV 极高，建议作为卖方或进行 Delta Neutral 对冲"
        elif ir < 20:
            return "IV 极低，适合买入波动率或跨式策略"
        return "波动率处于历史均值，保持观望或按常规交易"

    # ──────────────────────────────────────────
    # 内部实现（使用 yfinance）
    # ──────────────────────────────────────────

    def _fetch_iv_surface(self, symbol: str) -> dict:
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            expirations = ticker.options
            if not expirations:
                return {"symbol": symbol, "surface": [], "chain": {}, "expirations": [], "strikes": []}

            surface_data = []
            chain_data = {}
            all_strikes = set()
            
            for exp in expirations[:4]:  # 最多分析 4 个到期日
                try:
                    chain = ticker.option_chain(exp)
                    calls = _clean_records(chain.calls[["strike", "impliedVolatility", "volume", "openInterest"]].to_dict("records"))
                    puts = _clean_records(chain.puts[["strike", "impliedVolatility", "volume", "openInterest"]].to_dict("records"))
                    
                    # 合并到期日曲面
                    strike_map = {}
                    for c in calls:
                        s = c["strike"]
                        strike_map[s] = {"expiration": exp, "strike": s, "call_iv": round(_safe_float(c.get("impliedVolatility")), 4), "put_iv": None}
                        all_strikes.add(s)
                    for p in puts:
                        s = p["strike"]
                        if s in strike_map:
                            strike_map[s]["put_iv"] = round(_safe_float(p.get("impliedVolatility")), 4)
                        else:
                            strike_map[s] = {"expiration": exp, "strike": s, "call_iv": None, "put_iv": round(_safe_float(p.get("impliedVolatility")), 4)}
                        all_strikes.add(s)
                    
                    surface_data.extend(list(strike_map.values()))
                    chain_data[exp] = {"calls": calls, "puts": puts}
                except Exception as e:
                    logger.warning(f"Failed to fetch option chain for {symbol} {exp}: {e}")

            return _deep_clean({
                "symbol": symbol, 
                "surface": surface_data, 
                "chain": chain_data,
                "expirations": expirations[:4],
                "strikes": sorted(list(all_strikes)),
                "generated_at": datetime.now().isoformat()
            })
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

            current_hv = _safe_float(hv_series.iloc[-1])
            hv_52w_high = _safe_float(hv_series.max())
            hv_52w_low = _safe_float(hv_series.min())

            iv_rank = (current_hv - hv_52w_low) / (hv_52w_high - hv_52w_low) * 100 if hv_52w_high != hv_52w_low else 50.0
            iv_rank = _safe_float(iv_rank, 50.0)

            return {
                "symbol": symbol,
                "current_iv": round(current_hv, 4),
                "iv_52w_high": round(hv_52w_high, 4),
                "iv_52w_low": round(hv_52w_low, 4),
                "iv_rank": round(iv_rank, 1),
                "iv_percentile": round(iv_rank, 1), # 简化：IV Rank 约等于百分位
                "lookback_days": lookback_days,
                "generated_at": datetime.now().isoformat(),
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
                            vol = _safe_float(row.get("volume", 0))
                            oi = _safe_float(row.get("openInterest", 0))
                            if oi > 0 and vol > oi * 10:
                                ratio = _safe_float(vol / oi)
                                unusual.append({
                                    "symbol": symbol,
                                    "expiration": exp,
                                    "strike": _safe_float(row.get("strike")),
                                    "option_type": opt_type,
                                    "volume": int(vol),
                                    "open_interest": int(oi),
                                    "volume_oi_ratio": round(ratio, 1),
                                    "iv": round(_safe_float(row.get("impliedVolatility", 0)), 4),
                                    "detected_at": datetime.now().isoformat(),
                                })
                except Exception:
                    pass

            return sorted(_deep_clean(unusual), key=lambda x: (x.get("volume_oi_ratio") or 0), reverse=True)
        except Exception as e:
            return []

    def _calc_pc_ratio(self, chain: dict) -> Optional[float]:
        """计算 Put/Call Volume Ratio"""
        try:
            total_call_vol = 0
            total_put_vol = 0
            for exp, data in chain.items():
                total_call_vol += sum(_safe_float(r.get("volume", 0)) for r in data.get("calls", []))
                total_put_vol += sum(_safe_float(r.get("volume", 0)) for r in data.get("puts", []))
            
            if total_call_vol > 0:
                ratio = _safe_float(total_put_vol / total_call_vol)
                return round(ratio, 2)
            return None
        except Exception:
            return None


# 全局单例
options_analysis_service = OptionsAnalysisService()
