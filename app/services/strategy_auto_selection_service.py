from __future__ import annotations

from typing import Any

from sqlalchemy import case, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.strategy import Strategy

_MAX_AUTO_SCAN_BATCH_SIZE = 10


class StrategyAutoSelectionService:
    """统一自动策略选择逻辑。

    目标：
    1. 避免自动任务永远只命中同一个策略；
    2. 优先补齐从未运行过的 active 策略；
    3. 对已经运行过的策略按 last_run_at 最久优先轮转；
    4. auto_scan_priority 用于显式调度分层；默认同权时保持公平轮转；
    5. builtin 仅作为同优先级下的加权偏好，而不是绝对垄断条件。
    """

    @staticmethod
    def resolve_scan_limit(limit: Any = None) -> int:
        default_limit = max(
            1,
            int(settings.AUTO_STRATEGY_SCAN_BATCH_SIZE or 1),
        )
        try:
            requested_limit = int(
                limit if limit is not None else default_limit,
            )
        except (TypeError, ValueError):
            requested_limit = default_limit
        return max(1, min(requested_limit, _MAX_AUTO_SCAN_BATCH_SIZE))

    @classmethod
    async def select_auto_scan_strategies(
        cls,
        session: AsyncSession,
        limit: Any = None,
    ) -> list[Strategy]:
        strategy_limit = cls.resolve_scan_limit(limit)
        stmt = (
            select(Strategy)
            .where(
                Strategy.is_active.is_(True),
                Strategy.auto_scan_enabled.is_(True),
            )
            .order_by(
                desc(Strategy.auto_scan_priority),
                case((Strategy.last_run_at.is_(None), 0), else_=1),
                Strategy.last_run_at.asc(),
                desc(Strategy.is_builtin),
                desc(Strategy.updated_at),
                Strategy.id.asc(),
            )
            .limit(strategy_limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
