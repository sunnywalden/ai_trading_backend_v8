"""V10.2-M2: 财报围栏服务 EarningsFenceService

围栏策略：
- 财报前 PREEARNING_DAYS 天：将持仓规模截断到正常限额的 50%（PREEARNING_SIZE_LIMIT）
- 财报后：依据实际 EPS vs 预期重新评估仓位，决定保持/加仓/平仓
- 宏观高风险事件（FOMC/NFP/CPI）：VaR 乘数已由 RegimeClassifier 覆盖，围栏仅影响新开仓

使用示例::

    fence_svc = EarningsFenceService()
    status = await fence_svc.get_fence_status(db, "AAPL")
    if status.active:
        adjusted_size = status.max_size_pct * requested_size
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import event_bus, Topics
from app.models.event_calendar import EventCalendarEntry, EventRiskLevel, EventType

logger = logging.getLogger(__name__)

PREEARNING_DAYS        = 1     # 财报前多少天触发围栏
PREEARNING_SIZE_LIMIT  = 0.50  # 最大允许仓位（相对正常限额比例）
POSTEARNING_HOLD_HOURS = 2     # 财报后等待多少小时再重新评估


@dataclass
class FenceStatus:
    """围栏状态快照"""
    active: bool
    reason: str
    event_id: Optional[int]
    event_type: Optional[str]
    event_date: Optional[datetime]
    max_size_pct: float          # 1.0 = 无限制，0.5 = 只允许 50%
    overridden: bool
    override_reason: Optional[str]


class EarningsFenceService:
    """
    财报 / 宏观日历围栏服务。

    保守原则：有疑问时宁可围栏。
    """

    async def get_fence_status(
        self,
        db: AsyncSession,
        symbol: str,
    ) -> FenceStatus:
        """返回 symbol 当前的围栏状态。

        逻辑：查询未来 N+1 天内的未处理 EARNINGS 事件，判断是否进入围栏窗口。
        """
        now = datetime.now(tz=timezone.utc)
        horizon = now + timedelta(days=PREEARNING_DAYS + 1)

        stmt = (
            select(EventCalendarEntry)
            .where(
                EventCalendarEntry.symbol     == symbol,
                EventCalendarEntry.event_type == EventType.EARNINGS,
                EventCalendarEntry.event_date >= now,
                EventCalendarEntry.event_date <= horizon,
                EventCalendarEntry.requires_fence == True,  # noqa: E712
            )
            .order_by(EventCalendarEntry.event_date)
            .limit(1)
        )
        row: Optional[EventCalendarEntry] = (await db.execute(stmt)).scalars().first()

        if row is None:
            return FenceStatus(
                active=False, reason="no upcoming earnings", event_id=None,
                event_type=None, event_date=None, max_size_pct=1.0,
                overridden=False, override_reason=None,
            )

        if row.fence_overridden:
            return FenceStatus(
                active=False, reason="fence overridden by operator",
                event_id=row.id, event_type=row.event_type, event_date=row.event_date,
                max_size_pct=1.0, overridden=True, override_reason=row.fence_override_reason,
            )

        return FenceStatus(
            active=True,
            reason=f"earnings in {(row.event_date - now).days}d: {row.title}",
            event_id=row.id,
            event_type=row.event_type,
            event_date=row.event_date,
            max_size_pct=PREEARNING_SIZE_LIMIT,
            overridden=False,
            override_reason=None,
        )

    async def apply_fence(self, db: AsyncSession, symbol: str) -> FenceStatus:
        """标记围栏已应用，并发布事件总线消息。"""
        status = await self.get_fence_status(db, symbol)
        if status.active and status.event_id:
            await db.execute(
                update(EventCalendarEntry)
                .where(EventCalendarEntry.id == status.event_id)
                .values(fence_applied=True, fence_applied_at=datetime.now(tz=timezone.utc))
            )
            await db.commit()
            await event_bus.publish(
                Topics.EVENT_CALENDAR_ALERT,
                {
                    "action": "fence_applied",
                    "symbol": symbol,
                    "event_id": status.event_id,
                    "max_size_pct": status.max_size_pct,
                    "reason": status.reason,
                },
            )
            logger.info(f"[EarningsFence] applied fence for {symbol}: {status.reason}")
        return status

    async def override_fence(
        self,
        db: AsyncSession,
        event_id: int,
        reason: str,
    ) -> bool:
        """人工覆盖围栏（运营后台调用）。"""
        result = await db.execute(
            update(EventCalendarEntry)
            .where(EventCalendarEntry.id == event_id)
            .values(
                fence_overridden=True,
                fence_override_reason=reason,
            )
        )
        await db.commit()
        # SQLAlchemy Result doesn't have a typed rowcount attribute in stubs, silence the checker
        affected = result.rowcount  # type: ignore[attr-defined]
        if affected:
            logger.info(f"[EarningsFence] fence overridden for event_id={event_id}, reason={reason}")
        return bool(affected)

    async def record_earnings_result(
        self,
        db: AsyncSession,
        symbol: str,
        eps_actual: float,
        revenue_actual: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> None:
        """财报实际数据录入，触发 EARNINGS_RESULT 事件。"""
        # 找最近一条该 symbol 的 EARNINGS 事件
        stmt = (
            select(EventCalendarEntry)
            .where(
                EventCalendarEntry.symbol     == symbol,
                EventCalendarEntry.event_type == EventType.EARNINGS,
            )
            .order_by(EventCalendarEntry.event_date.desc())
            .limit(1)
        )
        row: Optional[EventCalendarEntry] = (await db.execute(stmt)).scalars().first()
        if row is None:
            logger.warning(f"[EarningsFence] record_earnings_result: no event found for {symbol}")
            return

        row.eps_actual      = eps_actual
        row.revenue_actual  = revenue_actual
        db.add(row)
        await db.commit()

        payload = {
            "symbol":          symbol,
            "event_id":        row.id,
            "eps_estimate":    row.eps_estimate,
            "eps_actual":      eps_actual,
            "revenue_actual":  revenue_actual,
            "beat":            (eps_actual > (row.eps_estimate or 0)) if row.eps_estimate else None,
        }
        await event_bus.publish(Topics.EARNINGS_RESULT, payload)
        logger.info(f"[EarningsFence] earnings result recorded: {symbol} EPS={eps_actual}")

    async def get_active_fences(self, db: AsyncSession) -> list[dict]:
        """返回所有当前处于围栏窗口的资产摘要（供 API 使用）。"""
        now = datetime.now(tz=timezone.utc)
        horizon = now + timedelta(days=PREEARNING_DAYS + 1)
        stmt = (
            select(EventCalendarEntry)
            .where(
                EventCalendarEntry.event_type    == EventType.EARNINGS,
                EventCalendarEntry.event_date    >= now,
                EventCalendarEntry.event_date    <= horizon,
                EventCalendarEntry.requires_fence == True,  # noqa: E712
                EventCalendarEntry.fence_overridden == False,  # noqa: E712
            )
            .order_by(EventCalendarEntry.event_date)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "symbol":       r.symbol,
                "event_id":     r.id,
                "event_date":   r.event_date.isoformat(),
                "max_size_pct": PREEARNING_SIZE_LIMIT,
                "fence_applied": r.fence_applied,
            }
            for r in rows
        ]


# ── 模块级单例 ────────────────────────────────────────────────────────────────
earnings_fence_service = EarningsFenceService()
