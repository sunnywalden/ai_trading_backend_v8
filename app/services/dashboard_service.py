"""V9: Dashboard聚合服务"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.equity_snapshot import EquitySnapshot
from app.models.trading_plan import TradingPlan
from app.models.price_alert import AlertHistory
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    DashboardExposure,
    DashboardSignal,
    DashboardAction,
)
from app.broker.factory import make_option_broker_client
from app.services.option_exposure_service import OptionExposureService
from app.services.account_service import AccountService


class DashboardService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_summary(self, account_id: str) -> DashboardSummaryResponse:
        """聚合 Dashboard 所有数据"""
        # 1. 账户权益
        broker = make_option_broker_client()
        try:
            equity = await broker.get_equity()
        except Exception:
            equity = 0.0

        account_svc = AccountService(self.session, broker)
        try:
            acct_info = await account_svc.get_account_info(account_id)
            cash = acct_info.get("cash", 0.0) if acct_info else 0.0
        except Exception:
            cash = 0.0

        total_equity = float(equity) if equity else 0.0
        market_value = total_equity - cash

        # 2. 今日盈亏（从快照）
        today = date.today()
        yesterday = today - timedelta(days=1)

        today_snap = await self._get_snapshot(account_id, today)
        yesterday_snap = await self._get_snapshot(account_id, yesterday)

        daily_pnl = 0.0
        daily_return_pct = 0.0
        if today_snap and yesterday_snap:
            prev_eq = float(yesterday_snap.total_equity)
            if prev_eq > 0:
                daily_pnl = float(today_snap.total_equity) - prev_eq
                daily_return_pct = daily_pnl / prev_eq * 100

        # 3. MTD/YTD
        mtd_return_pct = await self._calc_period_return(account_id, today.replace(day=1), today)
        ytd_return_pct = await self._calc_period_return(account_id, today.replace(month=1, day=1), today)

        # 4. 计划执行率
        plan_stats = await self._get_plan_stats(account_id)
        active_plans = plan_stats["active"]
        executed_plans = plan_stats["executed"]
        total_plans = plan_stats["total"]
        plan_rate = executed_plans / max(total_plans, 1) * 100

        # 5. Greeks 水位
        exposure = DashboardExposure()
        try:
            expo_svc = OptionExposureService(self.session, broker)
            expo = await expo_svc.get_account_exposure(account_id)
            eq = expo.equity_usd or 1.0
            exposure = DashboardExposure(
                delta_pct=expo.total_delta_notional_usd / eq * 100,
                gamma_pct=expo.total_gamma_usd / eq * 100,
                vega_pct=expo.total_vega_usd / eq * 100,
                theta_pct=expo.total_theta_usd / eq * 100,
            )
        except Exception:
            pass

        # 6. 风险等级
        risk_level = self._assess_risk_level(exposure)

        # 7. 最近告警
        recent_signals = await self._get_recent_signals(account_id, limit=5)

        # 8. 待办事项
        pending_actions = await self._get_pending_actions(account_id)

        return DashboardSummaryResponse(
            account_id=account_id,
            total_equity=total_equity,
            cash=cash,
            market_value=market_value,
            daily_pnl=daily_pnl,
            daily_return_pct=round(daily_return_pct, 4),
            mtd_return_pct=round(mtd_return_pct, 4),
            ytd_return_pct=round(ytd_return_pct, 4),
            plan_execution_rate=round(plan_rate, 2),
            active_plans_count=active_plans,
            risk_level=risk_level,
            exposure=exposure,
            recent_signals=recent_signals,
            pending_actions=pending_actions,
        )

    async def _get_snapshot(self, account_id: str, d: date) -> Optional[EquitySnapshot]:
        stmt = select(EquitySnapshot).where(
            and_(EquitySnapshot.account_id == account_id, EquitySnapshot.snapshot_date == d)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _calc_period_return(self, account_id: str, start: date, end: date) -> float:
        stmt = select(EquitySnapshot).where(
            and_(
                EquitySnapshot.account_id == account_id,
                EquitySnapshot.snapshot_date >= start,
                EquitySnapshot.snapshot_date <= end,
            )
        ).order_by(EquitySnapshot.snapshot_date)
        result = await self.session.execute(stmt)
        snaps = list(result.scalars().all())
        if len(snaps) < 2:
            return 0.0
        first_eq = float(snaps[0].total_equity)
        last_eq = float(snaps[-1].total_equity)
        if first_eq <= 0:
            return 0.0
        return (last_eq - first_eq) / first_eq * 100

    async def _get_plan_stats(self, account_id: str) -> dict:
        stmt = select(
            TradingPlan.plan_status, func.count(TradingPlan.id)
        ).where(TradingPlan.account_id == account_id).group_by(TradingPlan.plan_status)
        result = await self.session.execute(stmt)
        rows = result.all()
        stats = {"active": 0, "executed": 0, "total": 0}
        for status, count in rows:
            stats["total"] += count
            if status == "ACTIVE":
                stats["active"] = count
            elif status == "EXECUTED":
                stats["executed"] = count
        return stats

    def _assess_risk_level(self, exposure: DashboardExposure) -> str:
        max_pct = max(abs(exposure.delta_pct), abs(exposure.gamma_pct), abs(exposure.vega_pct), abs(exposure.theta_pct))
        if max_pct > 80:
            return "EXTREME"
        elif max_pct > 60:
            return "HIGH"
        elif max_pct > 40:
            return "MEDIUM"
        return "LOW"

    async def _get_recent_signals(self, account_id: str, limit: int = 5) -> list[DashboardSignal]:
        stmt = select(AlertHistory).where(
            AlertHistory.account_id == account_id
        ).order_by(AlertHistory.trigger_time.desc()).limit(limit)
        result = await self.session.execute(stmt)
        signals = []
        for alert_hist in result.scalars().all():
            signals.append(DashboardSignal(
                symbol=alert_hist.symbol,
                signal_type="price_alert",
                message=f"{alert_hist.symbol} 价格触及 ${float(alert_hist.trigger_price):.2f}",
                timestamp=alert_hist.trigger_time,
                severity="warning",
            ))
        return signals

    async def _get_pending_actions(self, account_id: str) -> list[DashboardAction]:
        actions = []
        today = date.today()

        # 检查今日到期的计划
        stmt = select(func.count(TradingPlan.id)).where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.plan_status == "ACTIVE",
                TradingPlan.valid_until != None,
                func.date(TradingPlan.valid_until) == today,
            )
        )
        result = await self.session.execute(stmt)
        expiring = result.scalar() or 0
        if expiring > 0:
            actions.append(DashboardAction(
                action_type="plan_expiring",
                message=f"{expiring} 个计划今日到期",
                link="/plans",
            ))

        return actions
