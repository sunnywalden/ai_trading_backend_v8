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

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    async def _get_lifecycle_position_rows(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> list[dict[str, Any]]:
        from app.services.position_query_service import PositionQueryService

        return await PositionQueryService(db).get_active_positions(account_id)

    async def _get_broker_position_snapshot(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> dict[str, dict[str, Any]]:
        from app.engine.position_monitor import PositionMonitor

        return await PositionMonitor(db).get_positions_snapshot(account_id)

    def _broker_snapshot_to_position_rows(
        self,
        account_id: str,
        snapshot: dict[str, dict[str, Any]],
        *,
        source: str,
        mismatch_detected: bool,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol, payload in snapshot.items():
            qty = self._safe_float(payload.get("qty"))
            avg_cost = self._safe_float(payload.get("avg_cost"))
            current_price = self._safe_float(
                payload.get("current_price") or payload.get("market_price")
            )
            market_value = abs(qty) * current_price if current_price > 0 else 0.0
            pnl_pct = self._safe_float(payload.get("unrealized_pnl_pct"))
            unrealized_pnl = market_value * pnl_pct
            rows.append(
                {
                    "id": None,
                    "account_id": account_id,
                    "symbol": symbol,
                    "thesis_key": "broker-live",
                    "status": "ACTIVE" if abs(qty) > 0 else "FLAT",
                    "direction": "SHORT" if qty < 0 else "LONG",
                    "total_qty": abs(qty),
                    "filled_qty": abs(qty),
                    "open_qty": abs(qty),
                    "closed_qty": 0.0,
                    "avg_entry_price": avg_cost,
                    "realized_pnl": 0.0,
                    "unrealized_pnl_pct": pnl_pct,
                    "stop_loss_price": None,
                    "take_profit_price": None,
                    "max_holding_days": None,
                    "execution_path": "BROKER_LIVE",
                    "closing_reason": None,
                    "closing_source": None,
                    "exemption_active": False,
                    "exemption_detail": None,
                    "governance_flag": None,
                    "initial_signal_id": None,
                    "initial_signal_uid": None,
                    "latest_plan_id": None,
                    "opened_at": None,
                    "closed_at": None,
                    "last_action_at": None,
                    "created_at": None,
                    "truth_source": source,
                    "market_value": round(market_value, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "broker_live": True,
                    "lifecycle_mismatch_detected": mismatch_detected,
                }
            )
        rows.sort(key=lambda item: str(item.get("symbol") or ""))
        return rows

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

    async def get_positions_read_model(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> dict[str, Any]:
        """生产读接口用的持仓口径：broker live 优先，生命周期兜底。"""
        lifecycle_rows: list[dict[str, Any]] = []
        broker_snapshot: dict[str, dict[str, Any]] = {}

        try:
            lifecycle_rows = await self._get_lifecycle_position_rows(db, account_id)
        except Exception as exc:
            logger.debug("TruthSourceService lifecycle read-model failed: %s", exc)

        try:
            broker_snapshot = await self._get_broker_position_snapshot(db, account_id)
        except Exception as exc:
            logger.debug("TruthSourceService broker read-model failed: %s", exc)

        lifecycle_symbols = {
            str(row.get("symbol") or "") for row in lifecycle_rows if row.get("symbol")
        }
        broker_symbols = set(broker_snapshot.keys())
        mismatch_symbols = sorted(lifecycle_symbols.symmetric_difference(broker_symbols))
        mismatch_detected = bool(broker_symbols) and lifecycle_symbols != broker_symbols

        if broker_snapshot:
            source = "BROKER_LIVE_OVERRIDE" if mismatch_detected and lifecycle_rows else "BROKER_LIVE"
            return {
                "items": self._broker_snapshot_to_position_rows(
                    account_id,
                    broker_snapshot,
                    source=source,
                    mismatch_detected=mismatch_detected,
                ),
                "source": source,
                "active_positions": len(broker_snapshot),
                "broker_active_positions": len(broker_snapshot),
                "lifecycle_active_positions": len(lifecycle_rows),
                "mismatch_detected": mismatch_detected,
                "mismatch_symbols": mismatch_symbols,
            }

        if lifecycle_rows:
            items = [dict(row, truth_source="POSITION_LIFECYCLE", broker_live=False, lifecycle_mismatch_detected=False) for row in lifecycle_rows]
            return {
                "items": items,
                "source": "POSITION_LIFECYCLE_FALLBACK",
                "active_positions": len(items),
                "broker_active_positions": 0,
                "lifecycle_active_positions": len(items),
                "mismatch_detected": False,
                "mismatch_symbols": [],
            }

        return {
            "items": [],
            "source": "EMPTY",
            "active_positions": 0,
            "broker_active_positions": 0,
            "lifecycle_active_positions": 0,
            "mismatch_detected": False,
            "mismatch_symbols": [],
        }


truth_source_service = TruthSourceService()
