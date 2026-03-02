"""execution_microscope_service.py — V10.3.3 执行显微镜服务

Implementation Shortfall (IS) 四分解:
  delay_cost:      决策到实际下单的时间窗口内价格漂移
  market_impact:   因本笔订单导致的价格冲击
  opportunity_cost: 因未成交部分造成的机会损失
  timing_cost:     时机选择相对于 arrival price 的成本

所有结果写入 execution_quality_log 表。
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_quality_log import ExecutionQualityLog
from app.models.execution_intent import AutonomousExecutionIntent

logger = logging.getLogger(__name__)

# 门限常数
GRADE_THRESHOLDS = {
    "A": (0, 5),    # IS < 5 bps
    "B": (5, 15),
    "C": (15, 30),
    "D": (30, 60),
    "F": (60, 9999),
}


def _grade(total_is_bps: float) -> str:
    for grade, (lo, hi) in GRADE_THRESHOLDS.items():
        if lo <= total_is_bps < hi:
            return grade
    return "F"


def _quality_score(total_is_bps: float, fill_rate: float) -> float:
    """综合执行质量分 0~100（IS 越小、成交率越高 → 分越高）。"""
    is_score = max(0.0, 100 - total_is_bps * 2)  # IS 每多 0.5bps 扣 1 分
    fill_score = fill_rate * 100
    return round(is_score * 0.6 + fill_score * 0.4, 2)


class ExecutionMicroscopeService:
    """对已完成 ExecutionIntent 计算 IS 四分解并落库。"""

    # ---------- 核心计算 ----------

    @staticmethod
    def compute_is_decomposition(
        arrival_price: float,
        fill_price: float,
        mid_at_order: float,
        vwap: float,
        quantity_ordered: float,
        quantity_filled: float,
        time_to_fill_ms: int,
        direction: str = "BUY",  # BUY or SELL
    ) -> dict[str, float]:
        """
        返回 IS 四分解结果（单位 bps）。

        IS = (fill_price - arrival_price) / arrival_price * 10000  (BUY)
        IS = (arrival_price - fill_price) / arrival_price * 10000  (SELL)

        分解：
          delay_cost      = (mid_at_order - arrival_price) / arrival_price * 10000
          market_impact   = (fill_price - mid_at_order) / arrival_price * 10000
          opportunity_cost = (1 - fill_rate) * abs(vwap - arrival_price) / arrival_price * 10000
          timing_cost      = total_IS - delay - impact - opportunity
        """
        if not arrival_price or arrival_price == 0:
            return {k: 0.0 for k in ("delay_cost_bps", "market_impact_bps", "opportunity_cost_bps", "timing_cost_bps", "total_is_bps")}

        sign = 1 if direction == "BUY" else -1
        fill_rate = quantity_filled / quantity_ordered if quantity_ordered > 0 else 0.0

        delay_cost_bps = sign * (mid_at_order - arrival_price) / arrival_price * 10000
        market_impact_bps = sign * (fill_price - mid_at_order) / arrival_price * 10000
        opportunity_cost_bps = (1 - fill_rate) * abs(vwap - arrival_price) / arrival_price * 10000
        total_is_bps = sign * (fill_price - arrival_price) / arrival_price * 10000
        timing_cost_bps = total_is_bps - delay_cost_bps - market_impact_bps - opportunity_cost_bps

        return {
            "delay_cost_bps": round(delay_cost_bps, 4),
            "market_impact_bps": round(market_impact_bps, 4),
            "opportunity_cost_bps": round(opportunity_cost_bps, 4),
            "timing_cost_bps": round(timing_cost_bps, 4),
            "total_is_bps": round(total_is_bps, 4),
            "fill_rate": round(fill_rate, 4),
        }

    async def record_execution_quality(
        self,
        db: AsyncSession,
        *,
        intent_id: int,
        user_id: str,
        symbol: str,
        direction: str,
        arrival_price: float,
        fill_price: float,
        mid_at_order: float,
        vwap: float,
        quantity_ordered: float,
        quantity_filled: float,
        time_to_fill_ms: int,
        algo_type: str = "MARKET",
    ) -> ExecutionQualityLog:
        """计算 IS 分解后写入 execution_quality_log。"""
        decomp = self.compute_is_decomposition(
            arrival_price, fill_price, mid_at_order, vwap,
            quantity_ordered, quantity_filled, time_to_fill_ms, direction,
        )
        fill_rate = decomp.pop("fill_rate", 1.0)
        total_is = decomp["total_is_bps"]

        log = ExecutionQualityLog(
            intent_id=intent_id,
            symbol=symbol,
            user_id=user_id,
            arrival_price=arrival_price,
            fill_price=fill_price,
            mid_price_at_order=mid_at_order,
            vwap_reference=vwap,
            quantity_ordered=quantity_ordered,
            quantity_filled=quantity_filled,
            fill_rate=fill_rate,
            time_to_fill_ms=time_to_fill_ms,
            algo_type=algo_type,
            quality_score=_quality_score(abs(total_is), fill_rate),
            grade=_grade(abs(total_is)),
            **decomp,
        )
        db.add(log)
        await db.flush()
        logger.info("ExecutionMicroscope: intent=%s %s IS=%.2fbps grade=%s", intent_id, symbol, total_is, log.grade)
        return log

    # ---------- 查询 ----------

    async def get_quality_summary(
        self,
        db: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """返回最近 N 笔执行质量记录（摘要）。"""
        stmt = (
            select(ExecutionQualityLog)
            .where(ExecutionQualityLog.user_id == user_id)
            .order_by(desc(ExecutionQualityLog.created_at))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "total_is_bps": r.total_is_bps,
                "delay_cost_bps": r.delay_cost_bps,
                "market_impact_bps": r.market_impact_bps,
                "opportunity_cost_bps": r.opportunity_cost_bps,
                "timing_cost_bps": r.timing_cost_bps,
                "fill_rate": r.fill_rate,
                "quality_score": r.quality_score,
                "grade": r.grade,
                "algo_type": r.algo_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def get_fill_heatmap(
        self,
        db: AsyncSession,
        user_id: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """返回按 symbol × algo_type 聚合的平均 IS，用于热力图。"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                ExecutionQualityLog.symbol,
                ExecutionQualityLog.algo_type,
                func.avg(ExecutionQualityLog.total_is_bps).label("avg_is"),
                func.avg(ExecutionQualityLog.fill_rate).label("avg_fill_rate"),
                func.count().label("count"),
            )
            .where(
                ExecutionQualityLog.user_id == user_id,
                ExecutionQualityLog.created_at >= cutoff,
            )
            .group_by(ExecutionQualityLog.symbol, ExecutionQualityLog.algo_type)
            .order_by(desc("avg_is"))
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "symbol": r.symbol,
                "algo_type": r.algo_type,
                "avg_is_bps": round(r.avg_is or 0, 4),
                "avg_fill_rate": round(r.avg_fill_rate or 0, 4),
                "count": r.count,
            }
            for r in rows
        ]

    async def get_avg_is_by_date(
        self,
        db: AsyncSession,
        user_id: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """按日期返回平均 IS 趋势。"""
        from datetime import timedelta
        from sqlalchemy import cast, Date as SQLDate
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                cast(ExecutionQualityLog.created_at, SQLDate).label("date"),
                func.avg(ExecutionQualityLog.total_is_bps).label("avg_is"),
                func.count().label("count"),
            )
            .where(
                ExecutionQualityLog.user_id == user_id,
                ExecutionQualityLog.created_at >= cutoff,
            )
            .group_by("date")
            .order_by("date")
        )
        rows = (await db.execute(stmt)).all()
        return [
            {"date": str(r.date), "avg_is_bps": round(r.avg_is or 0, 4), "count": r.count}
            for r in rows
        ]


# 模块级单例
execution_microscope_service = ExecutionMicroscopeService()
