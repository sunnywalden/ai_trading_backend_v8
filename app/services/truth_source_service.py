"""V10.5.4: TruthSourceService — 统一运行时真源快照。

目标：把 positions / regime 的运行时真源选择逻辑集中到一处，避免
AutonomousEngine、Copilot、Situational Awareness 等模块各自实现一套优先级。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TruthSourceService:
    """运行时真源聚合服务。"""

    async def get_regime_truth_snapshot(self, db: AsyncSession) -> dict[str, Any]:
        """优先级：Redis runtime → DB latest MarketRegime → UNKNOWN fallback。"""
        try:
            from app.services.regime_strategy_allocator import (
                fetch_current_regime_from_redis,
            )

            runtime = await fetch_current_regime_from_redis()
            regime = str(runtime.get("regime") or "UNKNOWN").upper()
            if regime != "UNKNOWN":
                return {
                    "regime": regime,
                    "confidence": float(runtime.get("confidence") or 0.0),
                    "var_multiplier": float(runtime.get("var_multiplier") or 1.0),
                    "source": "REDIS_RUNTIME",
                }
        except Exception as exc:
            logger.debug("TruthSourceService regime runtime read failed: %s", exc)

        try:
            from app.models.market_regime import MarketRegime

            latest_regime = (
                await db.execute(
                    select(MarketRegime)
                    .order_by(desc(MarketRegime.classification_date))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest_regime is not None:
                return {
                    "regime": str(latest_regime.regime or "UNKNOWN").upper(),
                    "confidence": float(latest_regime.confidence or 0.0),
                    "var_multiplier": 1.0,
                    "source": "MARKET_REGIME_DB",
                }
        except Exception as exc:
            logger.debug("TruthSourceService regime DB fallback failed: %s", exc)

        return {
            "regime": "UNKNOWN",
            "confidence": 0.0,
            "var_multiplier": 1.0,
            "source": "UNKNOWN",
        }

    async def get_positions_truth_snapshot(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> dict[str, Any]:
        """优先级：PositionQueryService lifecycle → PositionMonitor broker snapshot → empty fallback。"""
        try:
            from app.services.position_query_service import PositionQueryService

            lifecycle_rows = await PositionQueryService(db).get_active_positions(account_id)
            if lifecycle_rows:
                positions: dict[str, dict[str, Any]] = {}
                for row in lifecycle_rows:
                    symbol = str(row.get("symbol") or "")
                    if not symbol:
                        continue
                    qty = float(row.get("open_qty") or row.get("total_qty") or 0.0)
                    avg_entry = float(row.get("avg_entry_price") or 0.0)
                    positions[symbol] = {
                        "qty": qty,
                        "current_price": avg_entry,
                        "market_price": avg_entry,
                        "avg_cost": avg_entry,
                        "source_position_id": row.get("id"),
                        "status": row.get("status"),
                        "truth_source": "POSITION_LIFECYCLE",
                    }
                if positions:
                    return {
                        "positions": positions,
                        "positions_count": len(positions),
                        "source": "POSITION_LIFECYCLE",
                    }
        except Exception as exc:
            logger.debug("TruthSourceService lifecycle positions failed: %s", exc)

        try:
            from app.engine.position_monitor import PositionMonitor

            broker_positions = await PositionMonitor(db).get_positions_snapshot(account_id)
            if broker_positions:
                return {
                    "positions": broker_positions,
                    "positions_count": len(broker_positions),
                    "source": "POSITION_MONITOR",
                }
        except Exception as exc:
            logger.debug("TruthSourceService position monitor fallback failed: %s", exc)

        return {
            "positions": {},
            "positions_count": 0,
            "source": "EMPTY",
        }


truth_source_service = TruthSourceService()
