"""risk_observability_service.py — V10.3.3 风险可观测性集群

功能：
1. 每 5 分钟采样一次五因子敞口（Market/HML/SMB/MOM/QMJ）写入 portfolio_factor_exposure
2. 实时计算 ES@97.5%（Expected Shortfall/CVaR）
3. 持仓相关性监控——相关性骤升 > CORRELATION_SPIKE_THRESHOLD=0.65 → CORRELATION_SPIKE 告警
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_factor_exposure import PortfolioFactorExposure

logger = logging.getLogger(__name__)

CORRELATION_SPIKE_THRESHOLD: float = 0.65


def _compute_es(returns: list[float], confidence: float = 0.975) -> float:
    """Expected Shortfall (CVaR) at given confidence level（单位 %）。"""
    if len(returns) < 10:
        return 0.0
    arr = np.sort(np.array(returns, dtype=float))
    cutoff_idx = int(len(arr) * (1 - confidence))
    tail = arr[:cutoff_idx] if cutoff_idx > 0 else arr[:1]
    return max(0.0, float(-np.mean(tail)))  # 返回非负损失


def _compute_var(returns: list[float], confidence: float = 0.99) -> float:
    """VaR at given confidence level（单位 %，返回正数损失）。"""
    if len(returns) < 10:
        return 0.0
    arr = np.sort(np.array(returns, dtype=float))
    cutoff_idx = int(len(arr) * (1 - confidence))
    return max(0.0, float(-arr[max(0, cutoff_idx - 1)]))


def _estimate_factor_betas(
    symbol_weights: dict[str, float],
    factor_betas_db: dict[str, dict[str, float]],
) -> dict[str, float]:
    """
    加权合并各标的因子 Beta → 组合因子敞口。
    factor_betas_db: {symbol: {market: 1.2, hml: -0.3, smb: 0.4, mom: 0.1, qmj: 0.2}}
    """
    portfolio: dict[str, float] = {f: 0.0 for f in ("market", "hml", "smb", "mom", "qmj")}
    total_weight = sum(symbol_weights.values())
    if total_weight == 0:
        return portfolio
    for symbol, w in symbol_weights.items():
        betas = factor_betas_db.get(symbol, {})
        for factor in portfolio:
            portfolio[factor] += (w / total_weight) * betas.get(factor, 1.0 if factor == "market" else 0.0)
    return {k: round(v, 4) for k, v in portfolio.items()}


class RiskObservabilityService:
    """风险可观测性——因子敞口快照 + ES@97.5% + 相关性告警。"""

    async def ensure_recent_snapshot(
        self,
        db: AsyncSession,
        user_id: str,
        max_staleness_minutes: int = 10,
    ) -> bool:
        """确保用户存在一条近期风险快照；必要时按实时数据自动补一条。"""
        stmt = (
            select(PortfolioFactorExposure)
            .where(PortfolioFactorExposure.user_id == user_id)
            .order_by(desc(PortfolioFactorExposure.snapshot_at))
            .limit(1)
        )
        latest = (await db.execute(stmt)).scalars().first()
        if latest and latest.snapshot_at:
            age = datetime.utcnow() - latest.snapshot_at
            if age <= timedelta(minutes=max_staleness_minutes):
                return False

        return await self.seed_snapshot_from_live_data(db, user_id)

    async def seed_snapshot_from_live_data(self, db: AsyncSession, user_id: str) -> bool:
        """从实时持仓/信号数据构建快照，解决冷启动或任务中断造成的空图问题。"""
        symbol_weights = await self._load_symbol_weights_from_plans(db, user_id)
        if not symbol_weights:
            symbol_weights = await self._load_symbol_weights_from_signals(db, user_id)
        if not symbol_weights:
            return False

        factor_betas = self._build_default_factor_betas(symbol_weights)
        returns_history = await self._load_returns_history(db, user_id)
        pairwise_corr = await self._load_pairwise_corr(db, user_id, list(symbol_weights.keys()))

        await self.take_snapshot(
            db,
            user_id=user_id,
            symbol_weights=symbol_weights,
            factor_betas=factor_betas,
            returns_history=returns_history,
            pairwise_corr=pairwise_corr,
        )
        return True

    async def _load_symbol_weights_from_plans(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> dict[str, float]:
        from app.models.trading_plan import TradingPlan

        stmt = (
            select(TradingPlan.symbol, TradingPlan.target_position, TradingPlan.entry_price)
            .where(
                TradingPlan.account_id == user_id,
                func.upper(TradingPlan.plan_status).in_(["ACTIVE", "PARTIAL"]),
            )
        )
        rows = (await db.execute(stmt)).all()

        weights: dict[str, float] = {}
        for r in rows:
            qty = float(r.target_position or 0)
            px = float(r.entry_price or 0)
            mv = abs(qty * px) if px > 0 else abs(qty)
            if mv <= 0:
                continue
            weights[r.symbol] = weights.get(r.symbol, 0.0) + mv
        return weights

    async def _load_symbol_weights_from_signals(
        self,
        db: AsyncSession,
        user_id: str,
        days: int = 7,
    ) -> dict[str, float]:
        """无持仓计划时，从近期信号强度构造近似权重。"""
        from app.models.trading_signal import TradingSignal

        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(TradingSignal.symbol, TradingSignal.signal_strength)
            .where(
                TradingSignal.user_id == user_id,
                TradingSignal.created_at >= cutoff,
            )
            .order_by(desc(TradingSignal.created_at))
            .limit(300)
        )
        rows = (await db.execute(stmt)).all()

        weights: dict[str, float] = {}
        for r in rows:
            s = abs(float(r.signal_strength or 0.0))
            if s <= 0:
                continue
            weights[r.symbol] = weights.get(r.symbol, 0.0) + s
        return weights

    async def _load_returns_history(
        self,
        db: AsyncSession,
        user_id: str,
        days: int = 30,
    ) -> list[float]:
        from app.models.trading_signal import TradingSignal

        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                TradingSignal.actual_return,
                TradingSignal.pnl_pct,
                TradingSignal.expected_return,
                TradingSignal.direction,
                TradingSignal.signal_strength,
            )
            .where(
                TradingSignal.user_id == user_id,
                TradingSignal.created_at >= cutoff,
            )
            .order_by(desc(TradingSignal.created_at))
            .limit(500)
        )
        rows = (await db.execute(stmt)).all()

        vals: list[float] = []
        for r in rows:
            v = r.actual_return
            if v is None:
                v = r.pnl_pct
            if v is None:
                if r.expected_return is not None:
                    sign = -1.0 if str(r.direction or "").upper() == "SHORT" else 1.0
                    v = float(r.expected_return) * sign
                elif r.signal_strength is not None:
                    # 末级回退：把信号强度映射到微小收益区间（±2%）
                    sign = -1.0 if str(r.direction or "").upper() == "SHORT" else 1.0
                    v = min(0.02, max(0.0, abs(float(r.signal_strength)) / 5000.0)) * sign
            if v is None:
                continue
            vals.append(float(v))
        return vals

    async def _load_pairwise_corr(
        self,
        db: AsyncSession,
        user_id: str,
        symbols: list[str],
        days: int = 14,
    ) -> dict[tuple[str, str], float]:
        from app.models.trading_signal import TradingSignal

        if len(symbols) < 2:
            return {}

        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(TradingSignal.symbol, TradingSignal.signal_strength, TradingSignal.created_at)
            .where(
                TradingSignal.user_id == user_id,
                TradingSignal.created_at >= cutoff,
                TradingSignal.symbol.in_(symbols),
            )
            .order_by(TradingSignal.symbol, TradingSignal.created_at)
        )
        rows = (await db.execute(stmt)).all()

        by_symbol: dict[str, list[float]] = {}
        for r in rows:
            by_symbol.setdefault(r.symbol, []).append(float(r.signal_strength or 0.0))

        keys = [k for k, v in by_symbol.items() if len(v) >= 5]
        if len(keys) < 2:
            return {}

        pairwise: dict[tuple[str, str], float] = {}
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a = by_symbol[keys[i]]
                b = by_symbol[keys[j]]
                m = min(len(a), len(b))
                if m < 5:
                    continue
                arr = np.array([a[-m:], b[-m:]], dtype=float)
                try:
                    with np.errstate(invalid="ignore", divide="ignore"):
                        c = np.corrcoef(arr)[0, 1]
                    if not math.isnan(float(c)) and not math.isinf(float(c)):
                        pairwise[(keys[i], keys[j])] = float(c)
                except Exception:
                    continue

        return pairwise

    @staticmethod
    def _build_default_factor_betas(symbol_weights: dict[str, float]) -> dict[str, dict[str, float]]:
        """缺少外部因子库时使用稳定默认 beta，不阻塞风险看板。"""
        return {
            sym: {"market": 1.0, "hml": 0.15, "smb": 0.10, "mom": 0.20, "qmj": 0.05}
            for sym in symbol_weights
        }

    async def take_snapshot(
        self,
        db: AsyncSession,
        user_id: str,
        symbol_weights: dict[str, float],
        factor_betas: dict[str, dict[str, float]],
        returns_history: list[float],
        pairwise_corr: dict[tuple[str, str], float] | None = None,
    ) -> PortfolioFactorExposure:
        """计算因子敞口快照并落库。"""
        factor_expose = _estimate_factor_betas(symbol_weights, factor_betas)

        # ES / VaR
        es = _compute_es(returns_history)
        var99 = _compute_var(returns_history)

        # 相关性
        corr_values = list(pairwise_corr.values()) if pairwise_corr else []
        avg_corr = float(np.mean(corr_values)) if corr_values else 0.0
        max_corr = float(max(corr_values)) if corr_values else 0.0
        spike = max_corr > CORRELATION_SPIKE_THRESHOLD

        # 最高相关对
        top_pair: str | None = None
        if pairwise_corr:
            k = max(pairwise_corr, key=lambda p: pairwise_corr.get(p, 0.0))
            top_pair = f"{k[0]}-{k[1]}"

        # 年化波动率
        vol_ann = float(np.std(returns_history) * math.sqrt(252)) if len(returns_history) >= 5 else None

        # 组合 Beta（用 market factor）
        port_beta = factor_expose.get("market")

        snap = PortfolioFactorExposure(
            user_id=user_id,
            snapshot_at=datetime.utcnow(),
            beta_market=factor_expose["market"],
            beta_hml=factor_expose["hml"],
            beta_smb=factor_expose["smb"],
            beta_mom=factor_expose["mom"],
            beta_qmj=factor_expose["qmj"],
            var_99=round(var99, 4),
            es_97_5=round(es, 4),
            volatility_annualized=round(vol_ann, 4) if vol_ann else None,
            avg_pairwise_corr=round(avg_corr, 4),
            max_pairwise_corr=round(max_corr, 4),
            correlation_spike=spike,
            top_corr_pair=top_pair,
            positions_count=len(symbol_weights),
            portfolio_beta=port_beta,
            weights_snapshot=symbol_weights,
        )
        db.add(snap)
        await db.flush()

        if spike:
            logger.warning(
                "CORRELATION_SPIKE: user=%s max_corr=%.3f pair=%s",
                user_id, max_corr, top_pair,
            )
        return snap

    async def get_latest_snapshot(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, Any] | None:
        """返回最新快照。"""
        stmt = (
            select(PortfolioFactorExposure)
            .where(PortfolioFactorExposure.user_id == user_id)
            .order_by(desc(PortfolioFactorExposure.snapshot_at))
            .limit(1)
        )
        snap = (await db.execute(stmt)).scalars().first()
        return _snap_to_dict(snap) if snap else None

    async def get_risk_cluster(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, Any]:
        """返回完整风险仪表板数据。"""
        await self.ensure_recent_snapshot(db, user_id)
        latest = await self.get_latest_snapshot(db, user_id)
        history = await self.get_factor_exposure_history(db, user_id, hours=24)
        alerts = await self.get_correlation_alerts(db, user_id)
        return {
            "latest_snapshot": latest,
            "exposure_history_24h": history,
            "correlation_alerts": alerts,
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def get_factor_exposure_history(
        self,
        db: AsyncSession,
        user_id: str,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """返回最近 N 小时的因子敞口时间序列。"""
        await self.ensure_recent_snapshot(db, user_id)
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = (
            select(PortfolioFactorExposure)
            .where(
                PortfolioFactorExposure.user_id == user_id,
                PortfolioFactorExposure.snapshot_at >= cutoff,
            )
            .order_by(PortfolioFactorExposure.snapshot_at)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_snap_to_dict(r) for r in rows]

    async def get_correlation_alerts(
        self, db: AsyncSession, user_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """返回最近触发相关性骤升的快照。"""
        await self.ensure_recent_snapshot(db, user_id)
        stmt = (
            select(PortfolioFactorExposure)
            .where(
                PortfolioFactorExposure.user_id == user_id,
                PortfolioFactorExposure.correlation_spike.is_(True),
            )
            .order_by(desc(PortfolioFactorExposure.snapshot_at))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_snap_to_dict(r) for r in rows]


def _snap_to_dict(snap: PortfolioFactorExposure) -> dict[str, Any]:
    return {
        "id": snap.id,
        "snapshot_at": snap.snapshot_at.isoformat() if snap.snapshot_at else None,
        "beta_market": snap.beta_market,
        "beta_hml": snap.beta_hml,
        "beta_smb": snap.beta_smb,
        "beta_mom": snap.beta_mom,
        "beta_qmj": snap.beta_qmj,
        "es_97_5": snap.es_97_5,
        "var_99": snap.var_99,
        "volatility_annualized": snap.volatility_annualized,
        "avg_pairwise_corr": snap.avg_pairwise_corr,
        "max_pairwise_corr": snap.max_pairwise_corr,
        "correlation_spike": snap.correlation_spike,
        "top_corr_pair": snap.top_corr_pair,
        "positions_count": snap.positions_count,
        "portfolio_beta": snap.portfolio_beta,
    }


risk_observability_service = RiskObservabilityService()
