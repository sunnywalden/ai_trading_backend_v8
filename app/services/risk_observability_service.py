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
from sqlalchemy import select, desc
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
    return float(-np.mean(tail))  # 返回正数（损失）


def _compute_var(returns: list[float], confidence: float = 0.99) -> float:
    """VaR at given confidence level（单位 %，返回正数损失）。"""
    if len(returns) < 10:
        return 0.0
    arr = np.sort(np.array(returns, dtype=float))
    cutoff_idx = int(len(arr) * (1 - confidence))
    return float(-arr[max(0, cutoff_idx - 1)])


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
