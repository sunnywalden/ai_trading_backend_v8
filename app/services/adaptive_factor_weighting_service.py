"""adaptive_factor_weighting_service.py — V10.3.3 自适应因子权重服务

Kalman Filter 在线权重更新：
  state[t] = state[t-1] + K * (observation[t] - state[t-1])
  K = P / (P + R)   P = P_prev + Q

观测值 = 5 日 IC（Information Coefficient）

因子动量调整：
  TOP-2 IC 排名维度 +5%，末位维度 -5%，归一化至 100%

每日收盘后（16:30 EST）运行，写入 signal_weight_history。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal_weight_history import SignalWeightHistory

logger = logging.getLogger(__name__)

# Kalman 参数
KALMAN_Q: float = 0.001  # 过程噪声（权重漂移速度）
KALMAN_R: float = 0.01   # 观测噪声（IC 测量误差）

# 因子动量调整幅度（+ for top, - for bottom）
MOMENTUM_BONUS: float = 0.05
MOMENTUM_PENALTY: float = -0.05

# 初始权重（与 signal_fusion_engine._DIM_WEIGHTS 对齐）
DEFAULT_WEIGHTS: dict[str, float] = {
    "technical": 0.25,
    "fundamental": 0.20,
    "ml": 0.25,
    "sentiment": 0.10,
    "macro": 0.10,
    "event": 0.10,
}

# Kalman 状态缓存（内存，重启后从 DB 恢复）
_kalman_state: dict[str, dict[str, float]] = {}  # user_id → {dim: weight, dim_var: variance}


def _load_state(user_id: str) -> dict[str, float]:
    """从缓存加载 Kalman 状态（权重）。"""
    if user_id in _kalman_state:
        return {k: v for k, v in _kalman_state[user_id].items() if not k.endswith("_var")}
    return dict(DEFAULT_WEIGHTS)


def _load_variance(user_id: str) -> dict[str, float]:
    """加载状态协方差 P。"""
    if user_id in _kalman_state:
        return {
            dim: _kalman_state[user_id].get(f"{dim}_var", 0.1)
            for dim in DEFAULT_WEIGHTS
        }
    return {dim: 0.1 for dim in DEFAULT_WEIGHTS}


def _kalman_update(
    state: float, variance: float, observation: float, Q: float, R: float
) -> tuple[float, float, float]:
    """单维度 Kalman 更新。返回 (new_state, new_variance, kalman_gain)."""
    predicted_var = variance + Q
    kalman_gain = predicted_var / (predicted_var + R)
    new_state = state + kalman_gain * (observation - state)
    new_variance = (1 - kalman_gain) * predicted_var
    return new_state, new_variance, kalman_gain


def _apply_momentum_adjustment(
    weights: dict[str, float],
    ic_5d: dict[str, float],
) -> tuple[dict[str, float], dict[str, str]]:
    """
    TOP-2 IC 维度 +MOMENTUM_BONUS，最低 IC 维度 +MOMENTUM_PENALTY，
    最后归一化。返回 (调整后权重, 调整原因映射)。
    """
    sorted_dims = sorted(ic_5d, key=lambda d: ic_5d.get(d, 0.0), reverse=True)
    adjusted = dict(weights)
    reasons: dict[str, str] = {}

    top2 = sorted_dims[:2]
    bottom1 = sorted_dims[-1:]

    for dim in top2:
        adjusted[dim] = max(0.01, adjusted.get(dim, 0) + MOMENTUM_BONUS)
        reasons[dim] = "TOP2_BONUS"
    for dim in bottom1:
        if dim not in top2:
            adjusted[dim] = max(0.01, adjusted.get(dim, 0) + MOMENTUM_PENALTY)
            reasons[dim] = "BOTTOM_PENALTY"

    total = sum(adjusted.values())
    normalized = {k: round(v / total, 6) for k, v in adjusted.items()}
    for dim in weights:
        if dim not in reasons:
            reasons[dim] = "NO_ADJUST"
    return normalized, reasons


class AdaptiveFactorWeightingService:
    """Kalman Filter 自适应因子权重更新。"""

    async def run_daily_update(
        self,
        db: AsyncSession,
        user_id: str,
        ic_5d_by_dim: dict[str, float] | None = None,
        ic_20d_by_dim: dict[str, float] | None = None,
        ic_60d_by_dim: dict[str, float] | None = None,
    ) -> list[SignalWeightHistory]:
        """每日权重更新主入口。"""
        today = date.today()

        # 如已存在今日记录则跳过
        existing_check = await self._check_today_exists(db, user_id, today)
        if existing_check:
            logger.info("AdaptiveWeighting: already ran for %s user=%s", today, user_id)
            return []

        # 如果没有传入 IC，从 signal_intelligence_service 计算
        if ic_5d_by_dim is None:
            ic_5d_by_dim = await self._fetch_ic_from_db(db, user_id, window=5)
        if ic_20d_by_dim is None:
            ic_20d_by_dim = await self._fetch_ic_from_db(db, user_id, window=20)
        if ic_60d_by_dim is None:
            ic_60d_by_dim = await self._fetch_ic_from_db(db, user_id, window=60)

        # 从 DB 恢复最近权重（或用默认）
        prev_weights = await self._get_latest_weights_from_db(db, user_id) or _load_state(user_id)
        prev_variances = _load_variance(user_id)

        records = []
        new_weights = {}
        new_variances = {}
        kalman_gains = {}

        for dim in DEFAULT_WEIGHTS:
            observation = ic_5d_by_dim.get(dim, 0.0)
            new_state, new_var, k_gain = _kalman_update(
                prev_weights.get(dim, DEFAULT_WEIGHTS[dim]),
                prev_variances.get(dim, 0.1),
                observation,
                KALMAN_Q,
                KALMAN_R,
            )
            new_weights[dim] = max(0.01, new_state)
            new_variances[dim] = new_var
            kalman_gains[dim] = k_gain

        # 归一化
        total = sum(new_weights.values())
        new_weights = {k: round(v / total, 6) for k, v in new_weights.items()}

        # 动量调整
        momentum_weights, reasons = _apply_momentum_adjustment(new_weights, ic_5d_by_dim)

        # 更新内存缓存
        _kalman_state[user_id] = {**momentum_weights, **{f"{k}_var": v for k, v in new_variances.items()}}

        # 写入 DB
        for dim in DEFAULT_WEIGHTS:
            rec = SignalWeightHistory(
                user_id=user_id,
                record_date=today,
                dimension=dim,
                weight_before=round(prev_weights.get(dim, DEFAULT_WEIGHTS[dim]), 6),
                weight_after=round(new_weights[dim], 6),
                weight_momentum_adjusted=momentum_weights.get(dim),
                kalman_gain=round(kalman_gains[dim], 6),
                process_noise=KALMAN_Q,
                measurement_noise=KALMAN_R,
                posterior_variance=round(new_variances[dim], 6),
                ic_5d=ic_5d_by_dim.get(dim),
                ic_20d=ic_20d_by_dim.get(dim),
                ic_60d=ic_60d_by_dim.get(dim),
                ic_rank=None,  # 填充在批量 IC 排名后
                momentum_adjustment=MOMENTUM_BONUS if reasons.get(dim) == "TOP2_BONUS" else (MOMENTUM_PENALTY if reasons.get(dim) == "BOTTOM_PENALTY" else 0.0),
                adjustment_reason=reasons.get(dim),
                global_weights_snapshot=momentum_weights,
            )
            db.add(rec)
            records.append(rec)

        # 填充 IC 排名
        sorted_dims = sorted(ic_5d_by_dim, key=lambda d: ic_5d_by_dim.get(d, 0.0), reverse=True)
        for i, rec in enumerate(records):
            try:
                rank = sorted_dims.index(rec.dimension) + 1
                rec.ic_rank = rank
            except ValueError:
                pass

        await db.flush()
        logger.info("AdaptiveWeighting: updated weights for user=%s date=%s", user_id, today)
        return records

    async def get_current_weights(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, float]:
        """返回最新有效权重。"""
        weights = await self._get_latest_weights_from_db(db, user_id)
        return weights or dict(DEFAULT_WEIGHTS)

    async def get_weights_history(
        self, db: AsyncSession, user_id: str, days: int = 30, dimension: str | None = None
    ) -> list[dict[str, Any]]:
        """返回权重演化历史。"""
        cutoff = date.today() - timedelta(days=days)
        stmt = (
            select(SignalWeightHistory)
            .where(
                SignalWeightHistory.user_id == user_id,
                SignalWeightHistory.record_date >= cutoff,
            )
        )
        if dimension:
            stmt = stmt.where(SignalWeightHistory.dimension == dimension)
        stmt = stmt.order_by(SignalWeightHistory.record_date, SignalWeightHistory.dimension)

        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "record_date": str(r.record_date),
                "dimension": r.dimension,
                "weight_before": r.weight_before,
                "weight_after": r.weight_after,
                "weight_momentum_adjusted": r.weight_momentum_adjusted,
                "kalman_gain": r.kalman_gain,
                "ic_5d": r.ic_5d,
                "ic_20d": r.ic_20d,
                "ic_60d": r.ic_60d,
                "ic_rank": r.ic_rank,
                "adjustment_reason": r.adjustment_reason,
            }
            for r in rows
        ]

    async def get_factor_momentum(
        self, db: AsyncSession, user_id: str
    ) -> list[dict[str, Any]]:
        """返回最近各维度 IC 及动量因子排名。"""
        latest = await self.get_weights_history(db, user_id, days=1)
        return sorted(latest, key=lambda x: (x.get("ic_5d") or 0), reverse=True)

    async def _get_latest_weights_from_db(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, float] | None:
        """从 DB 恢复最新一天所有维度动量调整后权重。"""
        stmt = (
            select(SignalWeightHistory)
            .where(
                SignalWeightHistory.user_id == user_id,
                SignalWeightHistory.weight_momentum_adjusted.isnot(None),
            )
            .order_by(desc(SignalWeightHistory.record_date))
            .limit(len(DEFAULT_WEIGHTS) * 2)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            return None
        latest_date = max(r.record_date for r in rows)
        latest_rows = [r for r in rows if r.record_date == latest_date]
        weights = {
            r.dimension: r.weight_momentum_adjusted
            for r in latest_rows
            if r.dimension in DEFAULT_WEIGHTS and r.weight_momentum_adjusted is not None
        }
        return weights if weights else None

    async def _check_today_exists(
        self, db: AsyncSession, user_id: str, today: date
    ) -> bool:
        stmt = select(SignalWeightHistory.id).where(
            SignalWeightHistory.user_id == user_id,
            SignalWeightHistory.record_date == today,
        ).limit(1)
        row = (await db.execute(stmt)).first()
        return row is not None

    async def _fetch_ic_from_db(
        self, db: AsyncSession, user_id: str, window: int
    ) -> dict[str, float]:
        """从 signal_intelligence_service 获取最新 IC。"""
        from app.services.signal_intelligence_service import signal_intelligence_service, DIMENSIONS
        result = {}
        for dim in DIMENSIONS:
            try:
                data = await signal_intelligence_service.compute_dimension_ic(db, user_id, dim, window=window)
                ic_key = f"ic_{window}d"
                result[dim] = data.get(ic_key, 0.0) or 0.0
            except Exception:
                result[dim] = 0.0
        return result


adaptive_factor_weighting_service = AdaptiveFactorWeightingService()
