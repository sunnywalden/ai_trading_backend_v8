from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import Strategy, StrategyRun


async def get_research_home(db: AsyncSession) -> dict[str, Any]:
    try:
        total_strategies = (
            await db.execute(select(func.count()).select_from(Strategy))
        ).scalar_one()
        active_strategies = (
            await db.execute(
                select(func.count())
                .select_from(Strategy)
                .where(Strategy.is_active.is_(True))
            )
        ).scalar_one()
        latest_runs = list(
            (
                await db.execute(
                    select(StrategyRun).order_by(StrategyRun.created_at.desc()).limit(5)
                )
            )
            .scalars()
            .all()
        )
    except Exception:
        total_strategies = 0
        active_strategies = 0
        latest_runs = []

    return {
        "summary": {
            "total_strategies": int(total_strategies or 0),
            "active_strategies": int(active_strategies or 0),
            "recent_runs": len(latest_runs),
        },
        "recent_runs": [
            {
                "run_id": run.id,
                "strategy_id": run.strategy_id,
                "status": run.status,
                "direction": run.direction,
                "created_at": run.created_at,
            }
            for run in latest_runs
        ],
        "quick_actions": [
            {
                "label": "打开 Alpha Lab",
                "path": "/alpha-lab",
                "permission": "research.alpha_lab.read",
            },
            {
                "label": "查看机会扫描",
                "path": "/opportunities",
                "permission": "research.opportunities.read",
            },
            {
                "label": "浏览策略库",
                "path": "/strategies",
                "permission": "research.strategy.read",
            },
            {
                "label": "进入回测引擎",
                "path": "/backtest",
                "permission": "research.backtest.read",
            },
        ],
        "last_updated": datetime.utcnow().isoformat(),
    }
