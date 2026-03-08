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
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import Topics, event_bus
from app.models.event_calendar import EventCalendarEntry, EventRiskLevel, EventType
from app.models.trading_signal import TradingSignal

logger = logging.getLogger(__name__)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime:
    """返回某年某月第 n 个 weekday（Mon=0 ... Sun=6）的 UTC 日期（00:00）。"""
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    delta = (weekday - first.weekday()) % 7
    day = 1 + delta + (n - 1) * 7
    return datetime(year, month, day, tzinfo=timezone.utc)


def _build_macro_events_for_year(year: int) -> list[dict]:
    """构建滚动宏观事件（避免年份硬编码导致事件窗口为空）。"""
    records: list[dict] = []

    # FOMC：按常见开会月份给出近似日期（每月第 3 个周三，18:00 UTC）
    for month in (1, 3, 5, 6, 7, 9, 11, 12):
        dt = _nth_weekday_of_month(year, month, 2, 3).replace(hour=18)
        records.append(
            {
                "date": dt,
                "type": EventType.FOMC.value,
                "title": f"FOMC Rate Decision {dt.strftime('%b %Y')}",
                "risk": (
                    EventRiskLevel.HIGH.value
                    if month not in (11, 12)
                    else EventRiskLevel.EXTREME.value
                ),
            }
        )

    # NFP：每月第一个周五，13:30 UTC
    for month in range(1, 13):
        dt = _nth_weekday_of_month(year, month, 4, 1).replace(hour=13, minute=30)
        records.append(
            {
                "date": dt,
                "type": EventType.MACRO_DATA.value,
                "title": f"US Non-Farm Payrolls {dt.strftime('%b %Y')}",
                "risk": EventRiskLevel.HIGH.value,
            }
        )

    # CPI：每月第二个周三，13:30 UTC
    for month in range(1, 13):
        dt = _nth_weekday_of_month(year, month, 2, 2).replace(hour=13, minute=30)
        records.append(
            {
                "date": dt,
                "type": EventType.MACRO_DATA.value,
                "title": f"US CPI {dt.strftime('%b %Y')}",
                "risk": EventRiskLevel.HIGH.value,
            }
        )

    return records


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

        logger.info(
            f"[EventCalendar] scan complete. {len(new_entries)} new entries, symbols={len(symbols)}"
        )
        return new_entries

    async def resolve_scan_symbols(
        self, db: AsyncSession, limit: int = 60
    ) -> list[str]:
        """统一解析事件扫描标的：持仓 -> 最近信号 -> 本地全量池（兜底）。"""
        symbols: list[str] = []
        seen: set[str] = set()

        def _push(sym: Optional[str]) -> None:
            normalized = self._normalize_scan_symbol(sym)
            if not normalized:
                return
            if normalized in seen:
                return
            seen.add(normalized)
            symbols.append(normalized)

        # 1) 持仓口径（兼容不同状态命名）
        try:
            held = await db.execute(
                text(
                    """
                    SELECT DISTINCT symbol
                    FROM positions
                    WHERE symbol IS NOT NULL
                      AND (
                                                UPPER(status) IN (
                                                    'PENDING', 'OPENING', 'ACTIVE', 'SCALING_IN',
                                                    'SCALING_OUT', 'CLOSING', 'PARTIALLY_CLOSED', 'EXCEPTION'
                                                )
                                                OR COALESCE(open_qty, total_qty, 0) > 0
                      )
                    ORDER BY symbol
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            for row in held.fetchall():
                _push(row[0])
        except Exception as e:
            logger.warning(
                f"[EventCalendar] resolve symbols from positions failed: {e}"
            )

        # 2) 最近信号（避免持仓为空时完全无扫描）
        if len(symbols) < limit:
            try:
                rem = max(1, limit - len(symbols))
                cutoff = datetime.now(tz=timezone.utc) - timedelta(days=14)
                sig_rows = await db.execute(
                    select(TradingSignal.symbol)
                    .where(
                        TradingSignal.symbol.is_not(None),
                        TradingSignal.generated_at >= cutoff,
                    )
                    .group_by(TradingSignal.symbol)
                    .order_by(func.max(TradingSignal.generated_at).desc())
                    .limit(rem)
                )
                for row in sig_rows.fetchall():
                    _push(row[0])
            except Exception as e:
                logger.warning(
                    f"[EventCalendar] resolve symbols from signals failed: {e}"
                )

        # 3) 最终兜底样本，保证链路始终可产出数据，但避免打大量无效 ticker
        if not symbols:
            for s in ("AAPL", "MSFT", "NVDA", "TSLA", "QCOM", "ORCL"):
                _push(s)

        return symbols[:limit]

    @staticmethod
    def _normalize_scan_symbol(sym: Optional[str]) -> Optional[str]:
        if not sym:
            return None

        raw = str(sym).strip().upper()
        if not raw:
            return None

        # 指数 / 宏观符号不做财报扫描
        if raw.startswith(".") or raw == "MARKET":
            return None

        # 美股 warrant / rights / unit 等高噪声标的不做财报扫描
        if raw.endswith((".WS", ".W", ".U", ".R", "W")) and len(raw) >= 5:
            return None

        # 纯数字港股代码统一映射为 Yahoo Finance 可识别格式
        if re.fullmatch(r"\d{4,5}", raw):
            return f"{int(raw)}.HK"

        # 过滤明显异常 token
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", raw):
            return None

        return raw

    async def ensure_calendar_seeded(self, db: AsyncSession, days: int = 7) -> None:
        """确保窗口内至少有宏观事件；若数据库空白则触发轻量补扫描。"""
        now = datetime.now(tz=timezone.utc)
        horizon = now + timedelta(days=days)

        # 先补宏观事件（非常轻量）
        await self._upsert_macro_events(db, now, horizon)

        # 再检查是否仍为空；为空则按需触发一次扫描
        count_stmt = (
            select(EventCalendarEntry.id)
            .where(
                EventCalendarEntry.event_date >= now,
                EventCalendarEntry.event_date <= horizon,
            )
            .limit(1)
        )
        has_any = (await db.execute(count_stmt)).scalars().first()
        if has_any:
            return

        # 近窗口为空时加冷却阀，避免页面反复请求导致重复扫外部源
        seed_cooldown_key = f"event_calendar:seed_cooldown:{days}"
        try:
            from app.models.db import redis_client

            if redis_client and await redis_client.get(seed_cooldown_key):
                return
            if redis_client:
                await redis_client.setex(seed_cooldown_key, 600, "1")
        except Exception:
            pass

        symbols = await self.resolve_scan_symbols(db, limit=30)
        if symbols:
            await self.scan_and_upsert(
                db, symbols=symbols, lookahead_days=min(max(days, 3), 14)
            )

    # ── 内部：yfinance 财报日历 ─────────────────────────────────────────────

    async def _fetch_earnings_for_symbol(
        self,
        db: AsyncSession,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[EventCalendarEntry]:
        """通过 yfinance 获取财报日期，upsert 进库。"""
        fetch_symbol = self._normalize_scan_symbol(symbol)
        if not fetch_symbol:
            return []

        try:
            import yfinance as yf  # 懒导入，避免无 yf 环境报错

            ticker = yf.Ticker(fetch_symbol)
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
                        dt: datetime = dt_raw.to_pydatetime().replace(
                            tzinfo=timezone.utc
                        )
                    else:
                        dt = datetime.fromisoformat(str(dt_raw)).replace(
                            tzinfo=timezone.utc
                        )
                    if not (from_dt <= dt <= to_dt):
                        continue
                    # 查 duplicate
                    stmt = select(EventCalendarEntry).where(
                        EventCalendarEntry.symbol == symbol,
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
                    logger.warning(
                        f"[EventCalendar] parse earnings date error {symbol}: {inner}"
                    )
            await db.commit()
            return new_entries
        except Exception as e:
            logger.debug(f"[EventCalendar] yfinance fetch skipped/failed {symbol}: {e}")
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
        for year in range(from_dt.year - 1, to_dt.year + 2):
            for rec in _build_macro_events_for_year(year):
                try:
                    dt = rec["date"]
                    if not (from_dt <= dt <= to_dt):
                        continue
                    stmt = select(EventCalendarEntry).where(
                        EventCalendarEntry.event_type == rec["type"],
                        EventCalendarEntry.event_date == dt,
                        EventCalendarEntry.symbol == "MARKET",
                    )
                    existing = (await db.execute(stmt)).scalars().first()
                    if existing:
                        # 每次扫描都刷新 updated_at，让 freshness guard 知道扫描器仍在正常工作
                        existing.updated_at = datetime.now(timezone.utc).replace(
                            tzinfo=None
                        )
                        continue
                    entry = EventCalendarEntry(
                        symbol="MARKET",
                        event_type=rec["type"],
                        event_date=dt,
                        title=rec["title"],
                        risk_level=rec["risk"],
                        requires_fence=True,
                        source="hardcoded_dynamic",
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
        auto_seed_if_empty: bool = True,
    ) -> list[EventCalendarEntry]:
        """获取未来 days 天内的事件列表，可按 symbol 过滤。"""
        now = datetime.now(tz=timezone.utc)
        horizon = now + timedelta(days=days)

        if auto_seed_if_empty and not symbol:
            await self.ensure_calendar_seeded(db, days=days)

        stmt = (
            select(EventCalendarEntry)
            .where(
                EventCalendarEntry.event_date >= now,
                EventCalendarEntry.event_date <= horizon,
            )
            .order_by(EventCalendarEntry.event_date)
        )
        if symbol:
            stmt = stmt.where(EventCalendarEntry.symbol == symbol)
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        return self._dedupe_events(rows)

    @staticmethod
    def _event_key(entry: EventCalendarEntry) -> tuple[str, str, datetime, str]:
        """事件去重键：symbol + type + minute-level event_date + normalized title。"""
        dt = entry.event_date
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_minute = dt.replace(second=0, microsecond=0)
        return (
            (entry.symbol or "").strip().upper(),
            str(entry.event_type or "").strip().upper(),
            dt_minute,
            (entry.title or "").strip().lower(),
        )

    @staticmethod
    def _event_priority(entry: EventCalendarEntry) -> tuple[int, datetime, int]:
        """同 key 冲突时保留更“终态”的记录，避免同时出现已覆盖+待应用。"""
        # 优先级：overridden > applied > pending
        state_score = (
            3
            if bool(entry.fence_overridden)
            else (2 if bool(entry.fence_applied) else 1)
        )
        updated_at = entry.updated_at or entry.created_at or entry.event_date
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return (state_score, updated_at, int(entry.id or 0))

    def _dedupe_events(
        self, entries: list[EventCalendarEntry]
    ) -> list[EventCalendarEntry]:
        if len(entries) <= 1:
            return entries

        kept: dict[tuple[str, str, datetime, str], EventCalendarEntry] = {}
        for e in entries:
            key = self._event_key(e)
            old = kept.get(key)
            if old is None or self._event_priority(e) > self._event_priority(old):
                kept[key] = e

        out = list(kept.values())
        out.sort(key=lambda x: (x.event_date, x.symbol or "", x.id or 0))
        return out


# ── 模块级单例 ────────────────────────────────────────────────────────────────
event_calendar_service = EventCalendarService()
