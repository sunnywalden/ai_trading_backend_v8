"""signal_intelligence_service.py — V10.3.3 信号情报观察站

功能：
1. 计算六维因子 IC（5/20/60日）滚动序列
2. 计算 Alpha 半衰期 (alpha_halflife_days)
3. 拥挤度检测 —— crowding_score > 0.75 → 自动触发权重降低

IC (Information Coefficient) = Spearman 相关系数(预测值, 下期收益)
Alpha 半衰期：IC 衰减至 0.5 所需天数（基于 IC_t = IC_0 * (0.5)^(t/halflife)）
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SIGNAL_CROWDING_WARN: float = 0.75   # 拥挤度告警阈值
CROWDING_WEIGHT_REDUCE: float = 0.15  # 触发后权重降低幅度

# 因子维度（与 signal_fusion_engine 对齐）
DIMENSIONS = ["technical", "fundamental", "ml", "sentiment", "macro", "event"]


def _sanitize_json_compatible(value: Any) -> Any:
    """递归清洗 JSON 不兼容值（NaN/Inf/numpy 标量）。"""
    if value is None:
        return None

    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value

    module_name = type(value).__module__ or ""
    if module_name == "numpy" or module_name.startswith("numpy."):
        try:
            py_value = value.item() if hasattr(value, "item") else value
            if isinstance(py_value, float) and (math.isnan(py_value) or math.isinf(py_value)):
                return None
            return py_value
        except Exception:
            try:
                f = float(value)
                return None if (math.isnan(f) or math.isinf(f)) else f
            except Exception:
                return None

    if isinstance(value, dict):
        return {k: _sanitize_json_compatible(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_sanitize_json_compatible(v) for v in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_json_compatible(v) for v in value)

    return value


def _spearman_corr(predicted: list[float], realized: list[float]) -> float:
    """简易 Spearman 相关。requires len >= 3."""
    if len(predicted) < 3:
        return 0.0
    try:
        a = np.array(predicted, dtype=float)
        b = np.array(realized, dtype=float)
        ra = a.argsort().argsort().astype(float)
        rb = b.argsort().argsort().astype(float)
        n = len(a)
        num = np.sum((ra - ra.mean()) * (rb - rb.mean()))
        den = math.sqrt(np.sum((ra - ra.mean()) ** 2) * np.sum((rb - rb.mean()) ** 2))
        return float(num / den) if den > 0 else 0.0
    except Exception:
        return 0.0


def _compute_halflife(ic_series: list[float]) -> float:
    """
    用最小二乘拟合 IC_t = IC_0 * exp(-lambda * t)，
    返回半衰期 ln(2)/lambda 天。若无法计算返回 inf。
    """
    if len(ic_series) < 5:
        return float("inf")
    try:
        ics = np.array(ic_series, dtype=float)
        # 取绝对值防止对数域问题
        abs_ics = np.abs(ics)
        abs_ics = np.where(abs_ics < 1e-6, 1e-6, abs_ics)
        log_ics = np.log(abs_ics)
        t = np.arange(len(log_ics), dtype=float)
        slope, _ = np.polyfit(t, log_ics, 1)
        lam = -slope
        if lam <= 0:
            return float("inf")
        return round(math.log(2) / lam, 2)
    except Exception:
        return float("inf")


def _crowding_score(
    ic_5d: float,
    ic_stddev: float,
    sentiment_index: float = 0.5,  # 0~1
) -> float:
    """
    综合拥挤度分 0~1：
      - IC 过高（>0.1）且 stddev 极小 → 拥挤
      - sentiment_index 高 → 拥挤
    """
    ic_component = min(1.0, max(0.0, abs(ic_5d) / 0.15))
    stability_component = max(0.0, 1 - ic_stddev * 10)  # stddev 越小 → 拥挤分越高
    return round((ic_component * 0.5 + stability_component * 0.3 + sentiment_index * 0.2), 4)


class SignalIntelligenceService:
    """信号情报服务：IC 时间序列、Alpha 半衰期、拥挤度检测。"""

    async def compute_dimension_ic(
        self,
        db: AsyncSession,
        user_id: str,
        dimension: str,
        window: int = 60,
    ) -> dict[str, Any]:
        """
        从数据库读取最近 window 条信号预测值和实际收益，计算 5/20/60 日 IC。
        依赖 trading_signal 表中 dimension_scores 和 actual_return 字段。
        """
        from app.models.trading_signal import TradingSignal  # 延迟导入
        stmt = (
            select(TradingSignal)
            .where(
                TradingSignal.user_id == user_id,
            )
            .order_by(desc(TradingSignal.created_at))
            .limit(window)
        )
        try:
            rows = (await db.execute(stmt)).scalars().all()
        except Exception as e:
            logger.warning("SignalIntelligence: DB query failed: %s", e)
            rows = []

        # 提取预测信号和实际收益（如无 actual_return 字段则用 mock）
        predicted_series, realized_series = [], []
        for sig in reversed(rows):
            scores = getattr(sig, "dimension_scores", None) or {}
            score = scores.get(dimension, getattr(sig, "score", 0.0)) or 0.0
            realized = getattr(sig, "actual_return", None)
            if realized is not None:
                predicted_series.append(float(score))
                realized_series.append(float(realized))

        n = len(predicted_series)
        ic_5 = _spearman_corr(predicted_series[-5:], realized_series[-5:]) if n >= 5 else 0.0
        ic_20 = _spearman_corr(predicted_series[-20:], realized_series[-20:]) if n >= 20 else 0.0
        ic_60 = _spearman_corr(predicted_series, realized_series) if n >= 30 else 0.0

        # IC 系列用于半衰期
        rolling_ics = []
        step = max(1, n // 20)
        for i in range(5, n + 1, step):
            chunk_ic = _spearman_corr(predicted_series[:i], realized_series[:i])
            rolling_ics.append(chunk_ic)

        halflife = _compute_halflife(rolling_ics) if rolling_ics else float("inf")
        ic_stddev = float(np.std(rolling_ics)) if len(rolling_ics) > 2 else 0.0

        cs = _crowding_score(ic_5, ic_stddev)
        is_crowded = cs > SIGNAL_CROWDING_WARN

        return {
            "dimension": dimension,
            "ic_5d": round(ic_5, 6),
            "ic_20d": round(ic_20, 6),
            "ic_60d": round(ic_60, 6),
            "alpha_halflife_days": halflife,
            "ic_stddev": round(ic_stddev, 6),
            "crowding_score": cs,
            "is_crowded": is_crowded,
            "sample_count": n,
            "weight_reduce_triggered": is_crowded,
        }

    async def get_signal_intelligence(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> dict[str, Any]:
        """汇总所有维度 IC 状态。"""
        results = []
        for dim in DIMENSIONS:
            dim_data = await self.compute_dimension_ic(db, user_id, dim, window=60)
            results.append(dim_data)

        crowding_alerts = [r for r in results if r["is_crowded"]]
        payload = {
            "dimensions": results,
            "crowding_alerts": crowding_alerts,
            "crowding_alert_count": len(crowding_alerts),
            "updated_at": datetime.utcnow().isoformat(),
        }
        return _sanitize_json_compatible(payload)

    async def get_crowding_alerts(
        self, db: AsyncSession, user_id: str
    ) -> list[dict[str, Any]]:
        """仅返回触发拥挤度告警的维度。"""
        intel = await self.get_signal_intelligence(db, user_id)
        return intel["crowding_alerts"]

    async def get_signal_correlation_matrix(
        self,
        db: AsyncSession,
        user_id: str,
        symbols: list[str] | None = None,
        days: int = 20,
    ) -> dict[str, Any]:
        """
        计算近 days 日信号相关性矩阵（标的间）。
        如果 symbols 未指定则返回最多 10 个活跃标的。
        """
        from app.models.trading_signal import TradingSignal
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(TradingSignal.symbol, TradingSignal.signal_strength, TradingSignal.created_at)
            .where(
                TradingSignal.user_id == user_id,
                TradingSignal.created_at >= cutoff,
            )
            .order_by(TradingSignal.symbol, TradingSignal.created_at)
        )
        try:
            rows = (await db.execute(stmt)).all()
        except Exception:
            rows = []

        # 按标的分组
        series: dict[str, list[float]] = {}
        for r in rows:
            series.setdefault(r.symbol, []).append(float(r.signal_strength or 0))

        # 只取样本数≥5的标的，最多10个
        filtered = {k: v for k, v in series.items() if len(v) >= 5}
        if symbols:
            filtered = {k: v for k, v in filtered.items() if k in symbols}
        top_symbols = sorted(filtered.keys())[:10]

        if len(top_symbols) < 2:
            return {"symbols": top_symbols, "matrix": [], "updated_at": datetime.utcnow().isoformat()}

        # 对齐长度
        min_len = min(len(filtered[s]) for s in top_symbols)
        arr = np.array([filtered[s][-min_len:] for s in top_symbols], dtype=float)
        try:
            # 某些序列可能标准差为 0，np.corrcoef 会产生 runtime warning（invalid value encountered in divide）
            # 这里先做零方差识别，并在数值层面显式处理，避免噪音日志。
            stddev = np.std(arr, axis=1)
            valid_mask = stddev > 1e-12

            with np.errstate(invalid="ignore", divide="ignore"):
                corr_matrix = np.corrcoef(arr)

            # 对零方差序列对应的行/列统一置为 nan，随后由 _safe 清洗为 None
            for i, is_valid in enumerate(valid_mask):
                if not bool(is_valid):
                    corr_matrix[i, :] = np.nan
                    corr_matrix[:, i] = np.nan

            # 有效序列的对角线应为 1；无效序列保持 nan
            for i, is_valid in enumerate(valid_mask):
                corr_matrix[i, i] = 1.0 if bool(is_valid) else np.nan

            # 将 inf / -inf / nan 替换为 None（JSON 安全）
            def _safe(v: float):
                import math
                return None if (math.isnan(v) or math.isinf(v)) else round(float(v), 4)
            corr_list = [[_safe(v) for v in row] for row in corr_matrix]
        except Exception:
            corr_list = []

        payload = {
            "symbols": top_symbols,
            "matrix": corr_list,
            "updated_at": datetime.utcnow().isoformat(),
        }
        return _sanitize_json_compatible(payload)


signal_intelligence_service = SignalIntelligenceService()
