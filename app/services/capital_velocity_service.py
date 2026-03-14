"""V11.0.1 M1.1-1.4 — CapitalVelocityService

「资本速度评分」计算服务，满足产品需求 M1.1-1.4：
  - M1.1 CVS 核心计算（持仓转换速度 + 胜率加权）
  - M1.2 闲置资本检测（idle_cash_ratio 报告）
  - M1.3 仓位效率评级（A/B/C/D 效率分级）
  - M1.4 历史 CVS 对比分析

CVS（Capital Velocity Score）定义：
  score = weighted_turnover_rate * win_rate_bonus * regime_multiplier

  - weighted_turnover_rate：最近 20 个交易信号的加权周转率（按持仓市值加权）
  - win_rate_bonus：1 + realized_win_rate * 0.2（胜率奖励上限 0.20）
  - regime_multiplier：BULL_TREND → 1.1, BEAR_TREND → 0.9, NEUTRAL → 1.0

输出范围 0.0 ~ 200.0（标准化为 100 = 正常速度基准）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_CVS_BASELINE = 100.0  # 基准值（正常速度）
_LOOKBACK_SIGNALS = 20  # 计算窗口信号数
_LOOKBACK_DAYS = 30  # 历史分析天数
_IDLE_THRESHOLD = 0.25  # 闲置资本告警阈值

_REGIME_MULTIPLIER: dict[str, float] = {
    "BULL_TREND": 1.1,
    "BEAR_TREND": 0.9,
    "VOLATILE": 1.0,
    "NEUTRAL": 1.0,
}

# 仓位效率分级边界
_EFFICIENCY_GRADES = [
    (120.0, "A"),
    (90.0, "B"),
    (60.0, "C"),
]


@dataclass
class CapitalVelocityResult:
    """CVS 计算结果。"""

    account_id: str
    score: float  # 0.0 ~ 200.0
    turnover_rate: float  # 原始周转率
    win_rate: float  # 已实现胜率
    idle_cash_ratio: float  # 闲置资本比例
    efficiency_grade: str  # A / B / C / D
    regime: str
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    signal_count: int = 0  # 计算窗口内信号数量
    is_idle_alert: bool = False  # True 若 idle ratio > 阈值
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "score": round(self.score, 2),
            "turnover_rate": round(self.turnover_rate, 4),
            "win_rate": round(self.win_rate, 4),
            "idle_cash_ratio": round(self.idle_cash_ratio, 4),
            "efficiency_grade": self.efficiency_grade,
            "regime": self.regime,
            "computed_at": self.computed_at,
            "signal_count": self.signal_count,
            "is_idle_alert": self.is_idle_alert,
            "details": self.details,
        }


class CapitalVelocityService:
    """
    资本速度评分服务。

    使用示例::

        result = await cvs.compute_portfolio_velocity(
            db=session,
            account_id="ACC001",
            positions=positions,
            equity=905000.0,
            regime="BULL_TREND",
        )
    """

    async def compute_portfolio_velocity(
        self,
        *,
        db: AsyncSession,
        account_id: str,
        positions: dict[str, Any],
        equity: float,
        regime: Optional[str] = "NEUTRAL",
    ) -> CapitalVelocityResult:
        """
        计算账户资本速度评分（M1.1-1.4）。

        Args:
            db:         异步数据库会话
            account_id: 账户 ID
            positions:  当前持仓 {symbol: position_dict}
            equity:     当前账户净值
            regime:     市场体制标签
        """
        regime = regime or "NEUTRAL"
        regime_key = regime.upper()

        # M1.2 闲置资本
        idle_ratio = self._compute_idle_ratio(positions, equity)

        # M1.1 周转率 + 胜率
        turnover_rate, win_rate, signal_count = await self._compute_turnover(
            db=db, account_id=account_id, equity=equity
        )

        # CVS 合成
        regime_mult = _REGIME_MULTIPLIER.get(regime_key, 1.0)
        win_bonus = 1.0 + min(win_rate * 0.2, 0.20)
        raw_score = turnover_rate * win_bonus * regime_mult * _CVS_BASELINE
        score = min(max(raw_score, 0.0), 200.0)

        # M1.3 效率分级
        grade = _grade_efficiency(score)
        is_idle = idle_ratio > _IDLE_THRESHOLD

        return CapitalVelocityResult(
            account_id=account_id,
            score=score,
            turnover_rate=turnover_rate,
            win_rate=win_rate,
            idle_cash_ratio=idle_ratio,
            efficiency_grade=grade,
            regime=regime_key,
            signal_count=signal_count,
            is_idle_alert=is_idle,
            details={
                "regime_multiplier": regime_mult,
                "win_rate_bonus": round(win_bonus, 4),
                "idle_threshold": _IDLE_THRESHOLD,
                "lookback_signals": _LOOKBACK_SIGNALS,
            },
        )

    async def compute_historical_comparison(
        self,
        *,
        db: AsyncSession,
        account_id: str,
        equity: float,
        regime: Optional[str] = "NEUTRAL",
        days: int = 7,
    ) -> dict[str, Any]:
        """
        M1.4 历史 CVS 对比——返回指定天数的日均 CVS 趋势摘要。

        Returns:
            {"daily_scores": [...], "avg_score": float, "trend": "UP"|"DOWN"|"FLAT"}
        """
        regime = regime or "NEUTRAL"
        try:
            from app.models.trading_signal import TradingSignal

            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = (
                select(TradingSignal)
                .where(
                    and_(
                        TradingSignal.account_id == account_id,
                        TradingSignal.created_at >= cutoff,
                    )
                )
                .order_by(TradingSignal.created_at.asc())
            )
            result = await db.execute(stmt)
            signals = result.scalars().all()

            # 按天分组
            by_date: dict[str, list] = {}
            for sig in signals:
                day = sig.created_at.strftime("%Y-%m-%d")
                by_date.setdefault(day, []).append(sig)

            daily_scores: list[dict] = []
            for day_str, day_signals in sorted(by_date.items()):
                filled = sum(
                    1 for s in day_signals if getattr(s, "status", None) == "FILLED"
                )
                ratio = filled / max(len(day_signals), 1)
                daily_scores.append(
                    {
                        "date": day_str,
                        "score": round(ratio * _CVS_BASELINE, 2),
                        "signal_count": len(day_signals),
                        "fill_count": filled,
                    }
                )

            avg_score = (
                sum(d["score"] for d in daily_scores) / len(daily_scores)
                if daily_scores
                else 0.0
            )
            trend = _detect_trend([d["score"] for d in daily_scores])
            return {
                "daily_scores": daily_scores,
                "avg_score": round(avg_score, 2),
                "trend": trend,
            }
        except Exception as exc:
            logger.warning("[CVS] compute_historical_comparison: %s", exc)
            return {"daily_scores": [], "avg_score": 0.0, "trend": "FLAT"}

    # ──────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_idle_ratio(positions: dict[str, Any], equity: float) -> float:
        """M1.2 计算闲置资本比例。"""
        if equity <= 0:
            return 1.0
        try:
            gross = sum(
                abs(float(p.get("qty", 0) or 0))
                * abs(float(p.get("current_price", 0) or p.get("last_price", 0) or 0))
                for p in positions.values()
                if isinstance(p, dict)
            )
            return max(0.0, 1.0 - (gross / equity))
        except Exception:
            return 1.0

    @staticmethod
    async def _compute_turnover(
        *,
        db: AsyncSession,
        account_id: str,
        equity: float,
    ) -> tuple[float, float, int]:
        """
        M1.1 从最近 N 条 FILLED 信号计算平均周转率和胜率。

        Returns:
            (turnover_rate, win_rate, signal_count)
        """
        try:
            from app.models.trading_signal import TradingSignal

            stmt = (
                select(TradingSignal)
                .where(
                    and_(
                        TradingSignal.account_id == account_id,
                        TradingSignal.status == "FILLED",
                    )
                )
                .order_by(TradingSignal.created_at.desc())
                .limit(_LOOKBACK_SIGNALS)
            )
            result = await db.execute(stmt)
            sigs = result.scalars().all()

            if not sigs:
                return 1.0, 0.0, 0

            # 周转率 = Σ(|notional|) / (equity * len)，以 100 为基准
            total_notional = sum(
                abs(float(getattr(s, "quantity", 0) or 0))
                * abs(float(getattr(s, "price", 0) or 0))
                for s in sigs
            )
            if equity > 0 and len(sigs) > 0:
                turnover = (total_notional / equity) / len(sigs)
            else:
                turnover = 1.0

            # 胜率 = profit_realized > 0 的信号占比
            profitable = sum(
                1 for s in sigs if float(getattr(s, "realized_pnl", 0) or 0) > 0
            )
            win_rate = profitable / len(sigs) if sigs else 0.0

            return round(turnover, 6), round(win_rate, 4), len(sigs)
        except Exception as exc:
            logger.warning("[CVS] _compute_turnover: %s", exc)
            return 1.0, 0.0, 0


# ──────────────────────────────────────────────────────────────────
# Module-level helpers
# ──────────────────────────────────────────────────────────────────


def _grade_efficiency(score: float) -> str:
    """M1.3 仓位效率分级。"""
    for threshold, grade in _EFFICIENCY_GRADES:
        if score >= threshold:
            return grade
    return "D"


def _detect_trend(scores: list[float]) -> str:
    """简单线性趋势检测（最后3点均值 vs 前3点均值）。"""
    if len(scores) < 4:
        return "FLAT"
    mid = len(scores) // 2
    early = sum(scores[:mid]) / mid
    late_half = scores[mid:]
    late = sum(late_half) / len(late_half)
    if late > early * 1.05:
        return "UP"
    if late < early * 0.95:
        return "DOWN"
    return "FLAT"


# 单例
capital_velocity_service = CapitalVelocityService()
