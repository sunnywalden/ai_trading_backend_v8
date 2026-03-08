"""data_freshness_guard_service.py — V10.5.1 M4

数据陈旧度矩阵（Data Freshness Kill Matrix）。

检测以下数据源的时效性：
  1. quote_data      — 行情数据（通过 TechnicalIndicator 创建时间代理）
  2. positions       — 仓位数据（PortfolioSnapshot 更新时间）
  3. event_calendar  — 事件日历（EventCalendar 最新事件时间）
  4. factor_snapshot — 因子快照（PortfolioFactorExposure 更新时间）
  5. market_regime   — 市场体制（MarketRegime 最新分类时间）

每个数据源有对应的陈旧阈值：
  - quote_data:      stale > 2h    → WARNING / stale > 6h    → CRITICAL
  - positions:       stale > 4h    → WARNING / stale > 24h   → CRITICAL
  - event_calendar:  stale > 48h   → WARNING / stale > 120h  → CRITICAL
  - factor_snapshot: stale > 24h   → WARNING / stale > 72h   → CRITICAL
  - market_regime:   stale > 24h   → WARNING / stale > 72h   → CRITICAL

不同陈旧等级触发不同动作（在 autonomy_throttle_service 中使用）：
  OK       → 继续正常运行
  WARNING  → 降级至 SEMI
  CRITICAL → 冻结新开仓（仅允许减仓/平仓）
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

_OK = "OK"
_WARNING = "WARNING"
_CRITICAL = "CRITICAL"

# 每项数据源配置：(key, warn_hours, crit_hours, action_on_crit)
_SOURCE_CONFIG: list[tuple[str, float, float, str]] = [
    ("quote_data",      2.0,  6.0,   "DEGRADE_TO_SEMI"),
    ("positions",       4.0,  24.0,  "FREEZE_NEW_OPEN"),
    ("event_calendar",  48.0, 120.0, "DEGRADE_TO_SEMI"),
    ("factor_snapshot", 24.0, 72.0,  "DEGRADE_TO_SEMI"),
    ("market_regime",   24.0, 72.0,  "DEGRADE_TO_SEMI"),
]


def _age_hours(last_seen: datetime | None, now: datetime) -> float | None:
    if last_seen is None:
        return None
    delta = now - last_seen
    return delta.total_seconds() / 3600.0


def _classify(age_h: float | None, warn_h: float, crit_h: float) -> str:
    if age_h is None:
        return _CRITICAL  # 完全没有数据视为 CRITICAL
    if age_h >= crit_h:
        return _CRITICAL
    if age_h >= warn_h:
        return _WARNING
    return _OK


def _classify_missing_source(source_key: str, now: datetime) -> str:
    """对部分冷启动/休市场景做更温和的缺失分类。"""
    if source_key == "event_calendar" and now.weekday() >= 5:
        return _WARNING
    if source_key == "factor_snapshot":
        return _WARNING
    if source_key == "market_regime":
        return _WARNING
    return _CRITICAL


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _effective_thresholds(
    source_key: str,
    warn_h: float,
    crit_h: float,
    now: datetime,
) -> tuple[float, float]:
    """按交易时段动态放宽 freshness 阈值，避免休市期间误报。"""
    if source_key != "quote_data":
        return warn_h, crit_h

    # 周末：行情刷新通常停摆，不应按盘中阈值直接判 CRITICAL。
    if now.weekday() >= 5:
        return 24.0, 72.0

    # 粗粒度覆盖港股/美股的主要活跃时段（UTC）。
    utc_hour = now.hour
    hk_session_open = 1 <= utc_hour < 8
    us_session_open = 13 <= utc_hour < 21
    if hk_session_open or us_session_open:
        return warn_h, crit_h

    # 工作日非盘中：放宽到隔夜容忍窗口。
    return 12.0, 36.0


class DataFreshnessGuardService:
    """V10.5.1 M4 — 数据陈旧度守卫服务。"""

    # ── 各数据源最新时间查询 ─────────────────────────────────────────────

    @staticmethod
    async def _has_portfolio_risk_context(
        db: AsyncSession,
        keys: list[str],
    ) -> bool:
        try:
            from app.models.position import Position
            from app.models.trading_plan import TradingPlan

            pos_stmt = (
                select(Position.id)
                .where(Position.account_id.in_(keys))
                .limit(1)
            )
            if (await db.execute(pos_stmt)).scalar_one_or_none() is not None:
                return True

            plan_stmt = (
                select(TradingPlan.id)
                .where(
                    TradingPlan.account_id.in_(keys),
                    TradingPlan.plan_status.in_(["ACTIVE", "PARTIAL"]),
                )
                .limit(1)
            )
            return (
                (await db.execute(plan_stmt)).scalar_one_or_none() is not None
            )
        except Exception:
            return False

    @staticmethod
    async def _latest_quote(db: AsyncSession) -> datetime | None:
        try:
            from app.models.technical_indicator import TechnicalIndicator

            stmt = (
                select(TechnicalIndicator.timestamp)
                .order_by(desc(TechnicalIndicator.timestamp))
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            return row
        except Exception:
            return None

    @staticmethod
    async def _latest_position(
        db: AsyncSession,
        keys: list[str],
    ) -> datetime | None:
        try:
            from app.broker.factory import make_option_broker_client
            from app.models.position import Position

            stmt = (
                select(Position.updated_at)
                .where(Position.account_id.in_(keys))
                .order_by(desc(Position.updated_at))
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                return row

            # Fallback 1: account-agnostic internal positions,
            # 避免 account_id 口径不一致误判。
            stmt_any = (
                select(Position.updated_at)
                .order_by(desc(Position.updated_at))
                .limit(1)
            )
            result_any = await db.execute(stmt_any)
            row_any = result_any.scalar_one_or_none()
            if row_any is not None:
                return row_any

            # Fallback 2: 若本地无仓位记录，但 broker API 可正常返回（哪怕为空仓），
            # 说明仓位通道是新鲜的，不应冻结新开仓。
            broker = make_option_broker_client()
            account_id = keys[0] if keys else ""
            await broker.list_underlying_positions(
                account_id,
                force_refresh=True,
            )
            await broker.list_option_positions(account_id, force_refresh=True)
            return _utc_now_naive()
        except Exception:
            return None

    @staticmethod
    async def _latest_event(db: AsyncSession) -> datetime | None:
        try:
            from app.models.event_calendar import EventCalendarEntry
            from app.services.event_calendar_service import \
                event_calendar_service

            stmt = (
                select(EventCalendarEntry.created_at)
                .order_by(desc(EventCalendarEntry.created_at))
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                return row

            # 冷启动自愈：复用事件服务已有 seed 逻辑，先补宏观事件，再按需轻量扫描。
            await event_calendar_service.ensure_calendar_seeded(db, days=7)

            stmt = (
                select(EventCalendarEntry.created_at)
                .order_by(desc(EventCalendarEntry.created_at))
                .limit(1)
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except Exception:
            return None

    @staticmethod
    async def _latest_factor(
        db: AsyncSession,
        keys: list[str],
    ) -> datetime | None:
        try:
            from app.models.portfolio_factor_exposure import \
                PortfolioFactorExposure

            stmt = (
                select(PortfolioFactorExposure.snapshot_at)
                .where(PortfolioFactorExposure.account_id.in_(keys))
                .order_by(desc(PortfolioFactorExposure.snapshot_at))
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                return row

            stmt_any = (
                select(PortfolioFactorExposure.snapshot_at)
                .order_by(desc(PortfolioFactorExposure.snapshot_at))
                .limit(1)
            )
            result_any = await db.execute(stmt_any)
            row_any = result_any.scalar_one_or_none()
            if row_any is not None:
                return row_any

            # 空仓/无活跃计划场景下，因子快照不应被视为故障。
            if not await DataFreshnessGuardService._has_portfolio_risk_context(
                db, keys
            ):
                return _utc_now_naive()

            # 尝试即时补一张快照，解决冷启动窗口内 job 尚未运行的问题。
            from app.services.risk_observability_service import \
                risk_observability_service

            account_id = keys[0] if keys else ""
            seeded = await (
                risk_observability_service.seed_snapshot_from_live_data(
                    db,
                    account_id,
                )
            )
            if seeded:
                retry_stmt = (
                    select(PortfolioFactorExposure.snapshot_at)
                    .where(PortfolioFactorExposure.account_id.in_(keys))
                    .order_by(desc(PortfolioFactorExposure.snapshot_at))
                    .limit(1)
                )
                retry_result = await db.execute(retry_stmt)
                retry_row = retry_result.scalar_one_or_none()
                if retry_row is not None:
                    return retry_row
            return None
        except Exception:
            return None

    @staticmethod
    async def _latest_regime(db: AsyncSession) -> datetime | None:
        try:
            from app.models.market_regime import MarketRegime
            from app.services.regime_classifier import regime_classifier
            from app.services.regime_strategy_allocator import \
                fetch_current_regime_from_redis

            stmt = (
                select(MarketRegime.created_at)
                .order_by(desc(MarketRegime.created_at))
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                return row

            cached = await fetch_current_regime_from_redis()
            if cached.get("regime") and cached.get("regime") != "UNKNOWN":
                return _utc_now_naive()

            try:
                await regime_classifier.run(db)
                retry = await db.execute(stmt)
                return retry.scalar_one_or_none()
            except Exception:
                return None
        except Exception:
            return None

    # ── Public API ────────────────────────────────────────────────────────

    @staticmethod
    def _candidate_keys(account_id: str) -> list[str]:
        keys = [str(account_id)]
        if "@" in account_id:
            keys.append(account_id.split("@", 1)[0])
        if account_id.lower().startswith("user_"):
            keys.append(account_id[5:])
        return [k for idx, k in enumerate(keys) if k and k not in keys[:idx]]

    async def get_freshness_matrix(
        self,
        db: AsyncSession,
        account_id: str,
    ) -> dict[str, Any]:
        """返回所有数据源的陈旧度矩阵与总体最高风险等级。"""
        keys = self._candidate_keys(account_id)
        now = _utc_now_naive()

        latest_times: dict[str, datetime | None] = {
            "quote_data": await self._latest_quote(db),
            "positions": await self._latest_position(db, keys),
            "event_calendar": await self._latest_event(db),
            "factor_snapshot": await self._latest_factor(db, keys),
            "market_regime": await self._latest_regime(db),
        }

        matrix: list[dict[str, Any]] = []
        for source_key, warn_h, crit_h, action in _SOURCE_CONFIG:
            last_seen = latest_times.get(source_key)
            age_h = _age_hours(last_seen, now)
            effective_warn_h, effective_crit_h = _effective_thresholds(
                source_key, warn_h, crit_h, now
            )
            if age_h is None:
                status = _classify_missing_source(source_key, now)
            else:
                status = _classify(age_h, effective_warn_h, effective_crit_h)
            matrix.append(
                {
                    "source": source_key,
                    "last_seen": last_seen.isoformat() if last_seen else None,
                    "age_hours": (
                        round(age_h, 2) if age_h is not None else None
                    ),
                    "warn_threshold_hours": effective_warn_h,
                    "crit_threshold_hours": effective_crit_h,
                    "status": status,
                    "action_on_critical": action,
                }
            )

        critical_sources = [m for m in matrix if m["status"] == _CRITICAL]
        warning_sources = [m for m in matrix if m["status"] == _WARNING]

        if critical_sources:
            overall = _CRITICAL
        elif warning_sources:
            overall = _WARNING
        else:
            overall = _OK

        # 冻结新开仓标志：仓位数据 CRITICAL 时触发
        freeze_new_open = any(
            m["status"] == _CRITICAL
            and m["action_on_critical"] == "FREEZE_NEW_OPEN"
            for m in matrix
        )
        recommended_action: str
        if critical_sources:
            if freeze_new_open:
                recommended_action = "FREEZE_NEW_OPEN"
            else:
                recommended_action = "DEGRADE_TO_SEMI"
        elif warning_sources:
            recommended_action = "DEGRADE_TO_SEMI"
        else:
            recommended_action = "NONE"

        return {
            "as_of": now.isoformat(),
            "overall_status": overall,
            "critical_count": len(critical_sources),
            "warning_count": len(warning_sources),
            "critical_sources": [m["source"] for m in critical_sources],
            "freeze_new_open": freeze_new_open,
            "recommended_action": recommended_action,
            "matrix": matrix,
        }


data_freshness_guard_service = DataFreshnessGuardService()
