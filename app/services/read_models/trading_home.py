from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position, PositionStatus
from app.models.trading_plan import TradingPlan


async def get_trading_home(db: AsyncSession) -> dict[str, Any]:
    try:
        active_positions = (
            await db.execute(
                select(func.count())
                .select_from(Position)
                .where(
                    Position.status.in_(
                        [
                            PositionStatus.ACTIVE.value,
                            PositionStatus.OPENING.value,
                            PositionStatus.SCALING_IN.value,
                            PositionStatus.SCALING_OUT.value,
                            PositionStatus.CLOSING.value,
                            PositionStatus.PARTIALLY_CLOSED.value,
                        ]
                    )
                )
            )
        ).scalar_one()
        active_plans = (
            await db.execute(
                select(func.count())
                .select_from(TradingPlan)
                .where(TradingPlan.plan_status.in_(["ACTIVE", "PENDING", "EXECUTING"]))
            )
        ).scalar_one()
        latest_plans = list(
            (
                await db.execute(
                    select(TradingPlan).order_by(TradingPlan.updated_at.desc()).limit(5)
                )
            )
            .scalars()
            .all()
        )
    except Exception:
        active_positions = 0
        active_plans = 0
        latest_plans = []

    return {
        "summary": {
            "active_positions": int(active_positions or 0),
            "active_plans": int(active_plans or 0),
            "attention_items": sum(
                1
                for plan in latest_plans
                if str(plan.plan_status).upper() in {"FAILED", "EXCEPTION"}
            ),
        },
        "plan_snapshot": [
            {
                "plan_id": plan.id,
                "symbol": plan.symbol,
                "status": plan.plan_status,
                "direction": plan.direction,
                "confidence": (
                    float(plan.confidence) if plan.confidence is not None else None
                ),
                "updated_at": plan.updated_at,
            }
            for plan in latest_plans
        ],
        "quick_actions": [
            {
                "label": "智能订单簿",
                "path": "/order-book",
                "permission": "trading.order_book.read",
            },
            {
                "label": "执行策略控制台",
                "path": "/execution-policy",
                "permission": "trading.execution_policy.read",
            },
            {
                "label": "持仓监控",
                "path": "/positions",
                "permission": "trading.positions.read",
            },
            {
                "label": "交易日志",
                "path": "/journal",
                "permission": "trading.journal.read",
            },
        ],
        "last_updated": datetime.utcnow().isoformat(),
    }
