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
from sqlalchemy import select, desc, or_
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

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extract_dimension_score(self, sig: Any, dimension: str) -> float | None:
        """尽量从多种字段提取维度预测值，避免字段命名演进导致全 0。"""
        alias_map: dict[str, tuple[str, ...]] = {
            "technical": ("technical", "technical_score", "tech", "tech_score"),
            "fundamental": ("fundamental", "fundamental_score", "value_score"),
            "ml": ("ml", "ml_score", "model_score", "ai_score", "momentum_score"),
            "sentiment": ("sentiment", "sentiment_score", "news_sentiment"),
            "macro": ("macro", "macro_score", "regime_score"),
            "event": ("event", "event_score", "event_impact_score"),
        }
        candidate_keys = alias_map.get(dimension, (dimension,))

        containers = [
            getattr(sig, "dimension_scores", None),
            getattr(sig, "factor_scores", None),
            getattr(sig, "extra_metadata", None),
            getattr(sig, "tags", None),
        ]
        nested_keys = ("dimension_scores", "factor_scores", "dimensions", "scores")

        for c in containers:
            if not isinstance(c, dict):
                continue

            # 1) 直接维度键
            for key in candidate_keys:
                if key in c:
                    v = self._to_float(c.get(key))
                    if v is not None:
                        return v

            # 2) 常见嵌套结构
            for nk in nested_keys:
                nested = c.get(nk)
                if isinstance(nested, dict):
                    for key in candidate_keys:
                        if key in nested:
                            v = self._to_float(nested.get(key))
                            if v is not None:
                                return v

        # 3) 回退：信号强度（模型稳定可用）
        strength = self._to_float(getattr(sig, "signal_strength", None))
        if strength is not None:
            return strength

        # 4) 最后回退：confidence
        return self._to_float(getattr(sig, "confidence", None))

    @staticmethod
    def _compute_return_from_journal(
        entry_price: Any,
        exit_price: Any,
        realized_pnl: Any,
        quantity: Any,
        direction: str | None,
    ) -> float | None:
        e = SignalIntelligenceService._to_float(entry_price)
        x = SignalIntelligenceService._to_float(exit_price)
        pnl = SignalIntelligenceService._to_float(realized_pnl)
        qty = SignalIntelligenceService._to_float(quantity)

        side = (direction or "").upper()
        if e and e > 0 and x is not None:
            if side == "SHORT":
                return (e - x) / e
            return (x - e) / e

        if pnl is not None and qty and e and e > 0:
            base = abs(qty) * e
            if base > 0:
                return pnl / base

        return None

    async def _load_journal_return_map(
        self,
        db: AsyncSession,
        signal_ids: list[str],
    ) -> dict[str, float]:
        """从 trade_journal 按 signal_id 回退收益率，用于 actual_return 缺失场景。"""
        if not signal_ids:
            return {}

        from app.models.trade_journal import TradeJournal

        stmt = (
            select(
                TradeJournal.signal_id,
                TradeJournal.entry_price,
                TradeJournal.exit_price,
                TradeJournal.realized_pnl,
                TradeJournal.quantity,
                TradeJournal.direction,
                TradeJournal.updated_at,
            )
            .where(TradeJournal.signal_id.in_(signal_ids))
            .order_by(desc(TradeJournal.updated_at))
        )
        rows = (await db.execute(stmt)).all()

        mapped: dict[str, float] = {}
        for r in rows:
            sid = str(r.signal_id or "").strip()
            if not sid or sid in mapped:
                continue
            ret = self._compute_return_from_journal(
                r.entry_price,
                r.exit_price,
                r.realized_pnl,
                r.quantity,
                r.direction,
            )
            if ret is not None:
                mapped[sid] = float(ret)
        return mapped

    async def _load_latest_ic_from_weight_history(
        self,
        db: AsyncSession,
        account_id: str,
        dimension: str,
    ) -> tuple[float, float, float] | None:
        """当交易信号样本不足时，回退到 signal_weight_history 最新 IC。"""
        from app.models.signal_weight_history import SignalWeightHistory

        stmt = (
            select(SignalWeightHistory)
            .where(
                SignalWeightHistory.account_id == account_id,
                SignalWeightHistory.dimension == dimension,
            )
            .order_by(desc(SignalWeightHistory.record_date), desc(SignalWeightHistory.id))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalars().first()
        if not row:
            return None

        ic5 = self._to_float(row.ic_5d)
        ic20 = self._to_float(row.ic_20d)
        ic60 = self._to_float(row.ic_60d)
        if ic5 is None and ic20 is None and ic60 is None:
            return None
        return (ic5 or 0.0, ic20 or 0.0, ic60 or 0.0)

    async def compute_dimension_ic(
        self,
        db: AsyncSession,
        account_id: str,
        dimension: str,
        window: int = 60,
    ) -> dict[str, Any]:
        """
        从数据库读取最近 window 条信号预测值和实际收益，计算 5/20/60 日 IC。
        依赖 trading_signal 表中 dimension_scores 和 actual_return 字段。
        """
        # 确保关系映射已注册（TradingSignal.strategy -> Strategy）
        import app.models.strategy  # noqa: F401
        from app.models.trading_signal import TradingSignal  # 延迟导入
        stmt = (
            select(TradingSignal)
            .where(
                or_(
                    TradingSignal.user_id == account_id,
                    TradingSignal.account_id == account_id,
                ),
            )
            .order_by(desc(TradingSignal.created_at))
            .limit(window)
        )
        try:
            rows = (await db.execute(stmt)).scalars().all()
        except Exception as e:
            logger.warning("SignalIntelligence: DB query failed: %s", e)
            rows = []

        # actual_return 缺失时：尝试从 trade_journal 回退
        signal_ids = [str(getattr(sig, "signal_id", "") or "") for sig in rows if getattr(sig, "signal_id", None)]
        journal_return_map = {}
        try:
            journal_return_map = await self._load_journal_return_map(db, signal_ids)
        except Exception as e:
            logger.warning("SignalIntelligence: load journal fallback failed: %s", e)

        # 提取预测信号和实际收益
        predicted_series, realized_series = [], []
        proxy_predicted_series, proxy_realized_series = [], []
        for sig in reversed(rows):
            score = self._extract_dimension_score(sig, dimension)
            if score is None:
                continue

            realized = getattr(sig, "actual_return", None)
            if realized is None:
                realized = getattr(sig, "pnl_pct", None)
            if realized is None:
                sid = str(getattr(sig, "signal_id", "") or "")
                realized = journal_return_map.get(sid)
            if realized is not None:
                r = self._to_float(realized)
                if r is None:
                    continue
                predicted_series.append(float(score))
                realized_series.append(r)
            else:
                # 冷启动代理样本：当真实收益为空时，回退到 expected_return
                # 注意：该口径仅用于可观测性展示，data_quality 会标记为 PROXY。
                proxy_ret = self._to_float(getattr(sig, "expected_return", None))
                if proxy_ret is not None:
                    proxy_predicted_series.append(float(score))
                    proxy_realized_series.append(proxy_ret)

        if not predicted_series and len(proxy_predicted_series) >= 3:
            predicted_series = proxy_predicted_series
            realized_series = proxy_realized_series
            sample_source = "expected_return_proxy"
        else:
            sample_source = "trading_signals"

        n = len(predicted_series)
        ic_5 = _spearman_corr(predicted_series[-min(5, n):], realized_series[-min(5, n):]) if n >= 3 else 0.0
        ic_20 = _spearman_corr(predicted_series[-min(20, n):], realized_series[-min(20, n):]) if n >= 3 else 0.0
        ic_60 = _spearman_corr(predicted_series[-min(60, n):], realized_series[-min(60, n):]) if n >= 3 else 0.0

        # IC 系列用于半衰期
        rolling_ics = []
        step = max(1, n // 20) if n > 0 else 1
        for i in range(3, n + 1, step):
            chunk_ic = _spearman_corr(predicted_series[:i], realized_series[:i])
            rolling_ics.append(chunk_ic)

        # 冷启动回退：无样本时，优先使用 signal_weight_history 最新 IC
        # sample_source 在上文已根据真实/代理样本设定
        if n == 0:
            snapshot = await self._load_latest_ic_from_weight_history(db, account_id, dimension)
            if snapshot is not None:
                ic_5, ic_20, ic_60 = snapshot
                rolling_ics = [v for v in [ic_5, ic_20, ic_60] if v is not None]
                sample_source = "weight_history"
            else:
                sample_source = "empty"

        halflife = _compute_halflife(rolling_ics) if rolling_ics else float("inf")
        ic_stddev = float(np.std(rolling_ics)) if len(rolling_ics) > 2 else 0.0

        cs = _crowding_score(ic_5, ic_stddev)
        is_crowded = cs > SIGNAL_CROWDING_WARN

        # ── T1.2: data_quality 分级 ──
        # REAL          : 来自真实成交，样本 >= 10
        # INSUFFICIENT  : 真实样本 < 10（冷启动/新账户）
        # STALE         : 来自 weight_history（无近期真实样本）
        if sample_source == "trading_signals" and n >= 10:
            data_quality = "REAL"
        elif sample_source == "trading_signals" and n < 10:
            data_quality = "INSUFFICIENT"
        elif sample_source == "expected_return_proxy":
            data_quality = "PROXY"
        else:
            data_quality = "STALE"

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
            "sample_source": sample_source,
            "data_quality": data_quality,   # V10.4 M1 T1.2
        }

    async def get_signal_intelligence(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> dict[str, Any]:
        """汇总所有维度 IC 状态。"""
        results = []
        for dim in DIMENSIONS:
            dim_data = await self.compute_dimension_ic(db, account_id, dim, window=60)
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
        self, db: AsyncSession, account_id: str
    ) -> list[dict[str, Any]]:
        """仅返回触发拥挤度告警的维度。"""
        intel = await self.get_signal_intelligence(db, account_id)
        return intel["crowding_alerts"]

    async def get_signal_correlation_matrix(
        self,
        db: AsyncSession,
        account_id: str,
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
            select(
                TradingSignal.symbol,
                TradingSignal.signal_strength,
                TradingSignal.confidence,
                TradingSignal.expected_return,
                TradingSignal.created_at,
            )
            .where(
                or_(
                    TradingSignal.user_id == account_id,
                    TradingSignal.account_id == account_id,
                ),
                TradingSignal.created_at >= cutoff,
            )
            .order_by(TradingSignal.symbol, TradingSignal.created_at)
        )
        try:
            rows = (await db.execute(stmt)).all()
        except Exception:
            rows = []

        if not rows:
            fallback_stmt = (
                select(TradingSignal.symbol)
                .where(
                    or_(
                        TradingSignal.user_id == account_id,
                        TradingSignal.account_id == account_id,
                    )
                )
                .order_by(desc(TradingSignal.created_at))
                .limit(200)
            )
            fallback_rows = (await db.execute(fallback_stmt)).all()
            fallback_symbols: list[str] = []
            for r in fallback_rows:
                sym = str(r.symbol)
                if sym not in fallback_symbols:
                    fallback_symbols.append(sym)
                if len(fallback_symbols) >= 10:
                    break
            n = len(fallback_symbols)
            diag = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
            return {
                "symbols": fallback_symbols,
                "matrix": diag,
                "updated_at": datetime.utcnow().isoformat(),
            }

        # 按标的分组
        series: dict[str, list[float]] = {}
        for r in rows:
            # 优先 signal_strength；否则退化到 confidence / expected_return，避免全 0 方差
            v = self._to_float(r.signal_strength)
            if v is None or abs(v) < 1e-12:
                v = self._to_float(getattr(r, "confidence", None))
            if v is None or abs(v) < 1e-12:
                v = self._to_float(getattr(r, "expected_return", None))
            if v is None:
                v = 0.0
            series.setdefault(r.symbol, []).append(float(v))

        # 只取样本数≥2的标的，最多10个（降低门槛避免空白）
        filtered = {k: v for k, v in series.items() if len(v) >= 2}
        if symbols:
            filtered = {k: v for k, v in filtered.items() if k in symbols}
        top_symbols = sorted(filtered.keys())[:10]

        if len(top_symbols) < 2:
            # 降级：从所有序列里拿到最多 10 个活跃标的，返回对角矩阵
            fallback_symbols = sorted(series.keys())[:10]
            n = len(fallback_symbols)
            diag = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
            return {
                "symbols": fallback_symbols,
                "matrix": diag,
                "updated_at": datetime.utcnow().isoformat(),
            }

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

            # 对零方差序列对应的行/列统一置为 0，避免前端热力图出现整行空白
            for i, is_valid in enumerate(valid_mask):
                if not bool(is_valid):
                    corr_matrix[i, :] = 0.0
                    corr_matrix[:, i] = 0.0

            # 对角线固定为 1
            for i, is_valid in enumerate(valid_mask):
                corr_matrix[i, i] = 1.0

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
