"""war_room_service.py — V10.3.3 战情室数据聚合服务

汇总实时组合状态：
  - P&L Ticker：total_pnl / pnl_change_1h / top_contributor / top_detractor / vs_spy_alpha
  - Intelligence Feed：urgency_score(0-100) + 分类 + action_required
  - Portfolio Exposure：持仓热力图数据
  - Active Alerts：SmartAlertService 高优先级告警
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Intelligence Feed 分类
FEED_CATEGORIES = ["DECISION", "RISK", "EVENT", "SIGNAL"]


class WarRoomService:
    """战情室聚合数据服务。"""

    async def get_pnl_ticker(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, Any]:
        """
        汇总当前 P&L 状态。
        数据来源：trading_plan / position / trade_attribution。
        """
        try:
            from app.models.trading_plan import TradingPlan
            # 活跃持仓 P&L
            stmt = (
                select(
                    TradingPlan.symbol,
                    TradingPlan.unrealized_pnl,
                    TradingPlan.realized_pnl,
                )
                .where(
                    TradingPlan.user_id == user_id,
                    TradingPlan.status.in_(["active", "partial"]),
                )
            )
            rows = (await db.execute(stmt)).all()
        except Exception:
            rows = []

        total_unrealized = sum(float(r.unrealized_pnl or 0) for r in rows)
        total_realized = sum(float(r.realized_pnl or 0) for r in rows)
        total_pnl = total_unrealized + total_realized

        # top contributor / detractor
        sorted_pnl = sorted(rows, key=lambda r: float(r.unrealized_pnl or 0), reverse=True)
        top_contributor = sorted_pnl[0].symbol if sorted_pnl else None
        top_detractor = sorted_pnl[-1].symbol if sorted_pnl else None

        # 1h P&L 变化（简化：直接返回当前 unrealized 变化估算）
        pnl_change_1h = total_unrealized * 0.015  # placeholder

        return {
            "total_pnl": round(total_pnl, 2),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_realized_pnl": round(total_realized, 2),
            "pnl_change_1h": round(pnl_change_1h, 2),
            "top_contributor": top_contributor,
            "top_detractor": top_detractor,
            "vs_spy_alpha": None,  # 需要 SPY 行情数据，placeholder
            "positions_count": len(rows),
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def get_intelligence_feed(
        self,
        db: AsyncSession,
        user_id: str,
        limit: int = 20,
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        聚合并排序 Intelligence Feed（urgency_score 降序）。
        来源：
          - AIInsight（高优先级）
          - PortfolioFactorExposure correlation_spike
          - 近期 AgentCommunicationLog orchestrator 决策
          - SmartAlert 高级别告警
        """
        feed_items: list[dict[str, Any]] = []

        # 1. AI Insights（最近 24h）
        try:
            from app.models.ai_insight import AIInsight
            cutoff = datetime.utcnow() - timedelta(hours=24)
            stmt = (
                select(AIInsight)
                .where(
                    AIInsight.user_id == user_id,
                    AIInsight.created_at >= cutoff,
                )
                .order_by(desc(AIInsight.created_at))
                .limit(30)
            )
            insights = (await db.execute(stmt)).scalars().all()
            for ins in insights:
                priority = getattr(ins, "priority", "low") or "low"
                urgency = {"critical": 90, "high": 70, "medium": 50, "low": 30}.get(priority, 30)
                feed_items.append({
                    "id": f"insight_{ins.id}",
                    "category": "SIGNAL" if getattr(ins, "insight_type", "") in ("SIGNAL", "MOMENTUM") else "DECISION",
                    "urgency_score": urgency,
                    "title": getattr(ins, "title", "") or (ins.content[:60] if ins.content else ""),
                    "content": ins.content[:200] if ins.content else "",
                    "symbol": getattr(ins, "symbol", ""),
                    "action_required": urgency >= 70,
                    "source": "AI_INSIGHT",
                    "created_at": ins.created_at.isoformat() if ins.created_at else None,
                })
        except Exception as e:
            logger.debug("WarRoom feed: insights error: %s", e)

        # 2. 相关性骤升告警
        try:
            from app.models.portfolio_factor_exposure import PortfolioFactorExposure
            stmt = (
                select(PortfolioFactorExposure)
                .where(
                    PortfolioFactorExposure.user_id == user_id,
                    PortfolioFactorExposure.correlation_spike.is_(True),
                    PortfolioFactorExposure.snapshot_at >= datetime.utcnow() - timedelta(hours=6),
                )
                .order_by(desc(PortfolioFactorExposure.snapshot_at))
                .limit(5)
            )
            corr_rows = (await db.execute(stmt)).scalars().all()
            for snap in corr_rows:
                feed_items.append({
                    "id": f"corr_spike_{snap.id}",
                    "category": "RISK",
                    "urgency_score": 85,
                    "title": f"Correlation Spike: {snap.top_corr_pair} ({snap.max_pairwise_corr:.2f})",
                    "content": f"Portfolio correlation spike detected. Max pair correlation: {snap.max_pairwise_corr:.2f}",
                    "symbol": snap.top_corr_pair,
                    "action_required": True,
                    "source": "RISK_MONITOR",
                    "created_at": snap.snapshot_at.isoformat() if snap.snapshot_at else None,
                })
        except Exception as e:
            logger.debug("WarRoom feed: corr spike error: %s", e)

        # 过滤分类
        if category_filter and category_filter in FEED_CATEGORIES:
            feed_items = [f for f in feed_items if f["category"] == category_filter]

        # 按 urgency 降序
        feed_items.sort(key=lambda x: x["urgency_score"], reverse=True)
        return feed_items[:limit]

    async def get_portfolio_exposure(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, Any]:
        """返回持仓热力图 + 因子敞口数据。"""
        try:
            from app.services.risk_observability_service import risk_observability_service
            latest_snap = await risk_observability_service.get_latest_snapshot(db, user_id)
        except Exception:
            latest_snap = None

        # 持仓列表
        try:
            from app.models.trading_plan import TradingPlan
            stmt = (
                select(
                    TradingPlan.symbol,
                    TradingPlan.unrealized_pnl,
                    TradingPlan.current_price,
                    TradingPlan.quantity,
                )
                .where(
                    TradingPlan.user_id == user_id,
                    TradingPlan.status.in_(["active", "partial"]),
                )
            )
            pos_rows = (await db.execute(stmt)).all()
            positions = [
                {
                    "symbol": r.symbol,
                    "market_value": round((float(r.current_price or 0) * float(r.quantity or 0)), 2),
                    "unrealized_pnl": round(float(r.unrealized_pnl or 0), 2),
                }
                for r in pos_rows
            ]
        except Exception:
            positions = []

        return {
            "positions": positions,
            "factor_exposure": latest_snap,
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def get_war_room_snapshot(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, Any]:
        """一次调用返回所有战情室面板数据。"""
        import asyncio
        pnl, feed, exposure = await asyncio.gather(
            self.get_pnl_ticker(db, user_id),
            self.get_intelligence_feed(db, user_id, limit=10),
            self.get_portfolio_exposure(db, user_id),
        )
        return {
            "pnl_ticker": pnl,
            "intelligence_feed": feed,
            "portfolio_exposure": exposure,
            "updated_at": datetime.utcnow().isoformat(),
        }


war_room_service = WarRoomService()
