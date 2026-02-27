"""V10.2-M2: 事件日历服务 EventCalendarService

职责：
- 每日 07:00 扫描持仓中的股票，抓取未来 N 个交易日内的事件（财报/分红/宏观）
- 通过 yfinance 获取财报日历，通过 FRED/hard-coded 获取 FOMC/宏观日历
- 写入 / 更新 EventCalendarEntry，并由 EarningsFenceService 消费

依赖注入：
- `db: AsyncSession` 每次调用时传入
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import event_bus, Topics
from app.models.event_calendar import EventCalendarEntry, EventRiskLevel, EventType

logger = logging.getLogger(__name__)

# ── 宏观事件硬编码日历（2025 年简版，生产中应接 FRED/Refinitiv）────────────────────
_MACRO_EVENTS_2025: list[dict] = [
    # FOMC
    {"date": "2025-01-29", "type": EventType.FOMC, "title": "FOMC Rate Decision Jan 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-03-19", "type": EventType.FOMC, "title": "FOMC Rate Decision Mar 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-05-07", "type": EventType.FOMC, "title": "FOMC Rate Decision May 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-06-18", "type": EventType.FOMC, "title": "FOMC Rate Decision Jun 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-07-30", "type": EventType.FOMC, "title": "FOMC Rate Decision Jul 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-09-17", "type": EventType.FOMC, "title": "FOMC Rate Decision Sep 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-10-29", "type": EventType.FOMC, "title": "FOMC Rate Decision Oct 2025", "risk": EventRiskLevel.EXTREME},
    {"date": "2025-12-10", "type": EventType.FOMC, "title": "FOMC Rate Decision Dec 2025", "risk": EventRiskLevel.EXTREME},
    # Non-Farm Payrolls（每月第一个周五，此处列出前 6 个月）
    {"date": "2025-02-07", "type": EventType.MACRO_DATA, "title": "US Non-Farm Payrolls Feb 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-03-07", "type": EventType.MACRO_DATA, "title": "US Non-Farm Payrolls Mar 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-04-04", "type": EventType.MACRO_DATA, "title": "US Non-Farm Payrolls Apr 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-05-02", "type": EventType.MACRO_DATA, "title": "US Non-Farm Payrolls May 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-06-06", "type": EventType.MACRO_DATA, "title": "US Non-Farm Payrolls Jun 2025", "risk": EventRiskLevel.HIGH},
    # CPI
    {"date": "2025-01-15", "type": EventType.MACRO_DATA, "title": "US CPI Jan 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-02-12", "type": EventType.MACRO_DATA, "title": "US CPI Feb 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-03-12", "type": EventType.MACRO_DATA, "title": "US CPI Mar 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-04-10", "type": EventType.MACRO_DATA, "title": "US CPI Apr 2025", "risk": EventRiskLevel.HIGH},
    {"date": "2025-05-13", "type": EventType.MACRO_DATA, "title": "US CPI May 2025", "risk": EventRiskLevel.HIGH},
]


class EventCalendarService:
    """
    事件日历服务。

    典型调用流程::

        service = EventCalendarService()
        added = await service.scan_and_upsert(db, symbols=held_symbols, lookahead_days=5)
        # returned: list of EventCalendarEntry (newly-added only)
    """

    async def scan_and_upsert(
        self,
        db: AsyncSession,
        symbols: list[str],
        lookahead_days: int = 5,
    ) -> list[EventCalendarEntry]:
        """扫描未来 lookahead_days 个交易日内的事件并写库。

        Args:
            db:             异步数据库会话
            symbols:        当前持仓股票代码列表
            lookahead_days: 向前扫描天数（含今日）
        Returns:
            新写入的 EventCalendarEntry 列表
        """
        now = datetime.now(tz=timezone.utc)
        horizon = now + timedelta(days=lookahead_days + 2)  # 稍宽以覆盖周末
        new_entries: list[EventCalendarEntry] = []

        # 1. 抓取股票财报日历
        for symbol in symbols:
            entries = await self._fetch_earnings_for_symbol(db, symbol, now, horizon)
            new_entries.extend(entries)

        # 2. 注入宏观事件（硬编码 + FRED）
        macro_entries = await self._upsert_macro_events(db, now, horizon)
        new_entries.extend(macro_entries)

        # 3. 针对新事件发布总线通知
        for entry in new_entries:
            try:
                await event_bus.publish(Topics.EVENT_CALENDAR_ALERT, entry.to_dict())
            except Exception as e:
                logger.warning(f"[EventCalendar] publish alert failed: {e}")

        logger.info(f"[EventCalendar] scan complete. {len(new_entries)} new entries, symbols={len(symbols)}")
        return new_entries

    # ── 内部：yfinance 财报日历 ─────────────────────────────────────────────

    async def _fetch_earnings_for_symbol(
        self,
        db: AsyncSession,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[EventCalendarEntry]:
        """通过 yfinance 获取财报日期，upsert 进库。"""
        try:
            import yfinance as yf  # 懒导入，避免无 yf 环境报错

            ticker = yf.Ticker(symbol)
            cal = ticker.calendar  # DataFrame or dict
            if cal is None:
                return []

            # yfinance 返回 dict {'Earnings Date': [Timestamp, ...], ...}
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date", [])
            else:
                dates = cal.get("Earnings Date", []) if hasattr(cal, "get") else []

            new_entries = []
            for dt_raw in dates:
                try:
                    if hasattr(dt_raw, "to_pydatetime"):
                        dt: datetime = dt_raw.to_pydatetime().replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(str(dt_raw)).replace(tzinfo=timezone.utc)
                    if not (from_dt <= dt <= to_dt):
                        continue
                    # 查 duplicate
                    stmt = select(EventCalendarEntry).where(
                        EventCalendarEntry.symbol     == symbol,
                        EventCalendarEntry.event_type == EventType.EARNINGS,
                        EventCalendarEntry.event_date == dt,
                    )
                    existing = (await db.execute(stmt)).scalars().first()
                    if existing:
                        continue
                    entry = EventCalendarEntry(
                        symbol=symbol,
                        event_type=EventType.EARNINGS,
                        event_date=dt,
                        title=f"{symbol} Earnings",
                        risk_level=EventRiskLevel.HIGH,
                        requires_fence=True,
                        source="yfinance",
                    )
                    db.add(entry)
                    await db.flush()
                    new_entries.append(entry)
                except Exception as inner:
                    logger.warning(f"[EventCalendar] parse earnings date error {symbol}: {inner}")
            await db.commit()
            return new_entries
        except Exception as e:
            logger.error(f"[EventCalendar] yfinance fetch failed {symbol}: {e}")
            return []

    # ── 内部：宏观硬编码事件 upsert ──────────────────────────────────────────

    async def _upsert_macro_events(
        self,
        db: AsyncSession,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[EventCalendarEntry]:
        """将硬编码宏观日历中落在扫描窗口内的事件写入库（如尚不存在）。"""
        new_entries: list[EventCalendarEntry] = []
        for rec in _MACRO_EVENTS_2025:
            try:
                dt = datetime.strptime(rec["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if not (from_dt <= dt <= to_dt):
                    continue
                stmt = select(EventCalendarEntry).where(
                    EventCalendarEntry.event_type == rec["type"].value,
                    EventCalendarEntry.event_date == dt,
                    EventCalendarEntry.symbol == "MARKET",
                )
                existing = (await db.execute(stmt)).scalars().first()
                if existing:
                    continue
                entry = EventCalendarEntry(
                    symbol="MARKET",
                    event_type=rec["type"].value,
                    event_date=dt,
                    title=rec["title"],
                    risk_level=rec["risk"].value,
                    requires_fence=True,
                    source="hardcoded",
                )
                db.add(entry)
                await db.flush()
                new_entries.append(entry)
            except Exception as e:
                logger.warning(f"[EventCalendar] macro upsert error: {e}")
        await db.commit()
        return new_entries

    # ── 查询接口 ──────────────────────────────────────────────────────────────

    async def get_upcoming(
        self,
        db: AsyncSession,
        days: int = 7,
        symbol: Optional[str] = None,
    ) -> list[EventCalendarEntry]:
        """获取未来 days 天内的事件列表，可按 symbol 过滤。"""
        now = datetime.now(tz=timezone.utc)
        horizon = now + timedelta(days=days)
        stmt = select(EventCalendarEntry).where(
            EventCalendarEntry.event_date >= now,
            EventCalendarEntry.event_date <= horizon,
        ).order_by(EventCalendarEntry.event_date)
        if symbol:
            stmt = stmt.where(EventCalendarEntry.symbol == symbol)
        result = await db.execute(stmt)
        return list(result.scalars().all())


# ── 模块级单例 ────────────────────────────────────────────────────────────────
event_calendar_service = EventCalendarService()
