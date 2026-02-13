"""V9: 资金曲线与PnL归因服务"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.equity_snapshot import EquitySnapshot
from app.models.trade_pnl_attribution import TradePnlAttribution
from app.broker.factory import make_option_broker_client
from app.services.account_service import AccountService
from app.providers.market_data_provider import MarketDataProvider


class EquityService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_daily_snapshot(self, account_id: str) -> EquitySnapshot:
        """创建当日账户权益快照"""
        today = date.today()

        # 检查今日是否已有快照
        existing = await self._get_snapshot(account_id, today)
        if existing:
            return existing

        # 获取账户权益
        broker = make_option_broker_client()
        try:
            total_equity = float(await broker.get_equity())
        except Exception:
            total_equity = 0.0

        try:
            account_svc = AccountService(self.session, broker)
            info = await account_svc.get_account_info(account_id)
            cash = float(info.get("cash", 0)) if info else 0.0
        except Exception:
            cash = 0.0

        market_value = total_equity - cash

        # 计算日收益率
        yesterday = today - timedelta(days=1)
        prev_snap = await self._get_snapshot(account_id, yesterday)
        daily_return = None
        if prev_snap and float(prev_snap.total_equity) > 0:
            daily_return = (total_equity - float(prev_snap.total_equity)) / float(prev_snap.total_equity)

        # 计算累计收益率
        first_snap = await self._get_first_snapshot(account_id)
        cumulative_return = None
        if first_snap and float(first_snap.total_equity) > 0:
            cumulative_return = (total_equity - float(first_snap.total_equity)) / float(first_snap.total_equity)

        # 计算最大回撤
        max_dd = await self._calc_max_drawdown(account_id, total_equity)

        # 获取 SPY 基准
        benchmark_return = await self._get_benchmark_return()

        snapshot = EquitySnapshot(
            account_id=account_id,
            snapshot_date=today,
            total_equity=Decimal(str(round(total_equity, 2))),
            cash=Decimal(str(round(cash, 2))),
            market_value=Decimal(str(round(market_value, 2))),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal(str(round(market_value, 2))),
            daily_return=Decimal(str(round(daily_return, 6))) if daily_return is not None else None,
            cumulative_return=Decimal(str(round(cumulative_return, 6))) if cumulative_return is not None else None,
            max_drawdown_pct=Decimal(str(round(max_dd, 6))) if max_dd is not None else None,
            benchmark_return=Decimal(str(round(benchmark_return, 6))) if benchmark_return is not None else None,
        )
        self.session.add(snapshot)
        await self.session.commit()
        await self.session.refresh(snapshot)
        return snapshot

    async def get_snapshots(self, account_id: str, days: int = 30) -> list[EquitySnapshot]:
        """获取最近N天的权益快照"""
        start_date = date.today() - timedelta(days=days)
        stmt = select(EquitySnapshot).where(
            and_(
                EquitySnapshot.account_id == account_id,
                EquitySnapshot.snapshot_date >= start_date,
            )
        ).order_by(EquitySnapshot.snapshot_date)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pnl_attribution(
        self, account_id: str, group_by: str = "symbol",
        start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> list[dict]:
        """获取PnL归因"""
        if group_by == "symbol":
            group_col = TradePnlAttribution.symbol
        elif group_by == "strategy":
            group_col = TradePnlAttribution.strategy_tag
        else:
            group_col = TradePnlAttribution.symbol

        stmt = select(
            group_col,
            func.sum(TradePnlAttribution.realized_pnl),
            func.count(TradePnlAttribution.id),
        ).where(TradePnlAttribution.account_id == account_id)

        if start_date:
            stmt = stmt.where(TradePnlAttribution.trade_date >= start_date)
        if end_date:
            stmt = stmt.where(TradePnlAttribution.trade_date <= end_date)

        stmt = stmt.group_by(group_col).order_by(func.sum(TradePnlAttribution.realized_pnl).desc())
        result = await self.session.execute(stmt)
        rows = result.all()

        total_pnl = sum(float(r[1] or 0) for r in rows)
        attributions = []
        for label, pnl, count in rows:
            pnl_val = float(pnl or 0)
            attributions.append({
                "label": label or "未分类",
                "pnl": pnl_val,
                "pct": pnl_val / abs(total_pnl) * 100 if total_pnl != 0 else 0,
                "trade_count": count,
            })
        return attributions

    async def _get_snapshot(self, account_id: str, d: date) -> Optional[EquitySnapshot]:
        stmt = select(EquitySnapshot).where(
            and_(EquitySnapshot.account_id == account_id, EquitySnapshot.snapshot_date == d)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _get_first_snapshot(self, account_id: str) -> Optional[EquitySnapshot]:
        stmt = select(EquitySnapshot).where(
            EquitySnapshot.account_id == account_id
        ).order_by(EquitySnapshot.snapshot_date).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _calc_max_drawdown(self, account_id: str, current_equity: float) -> Optional[float]:
        stmt = select(func.max(EquitySnapshot.total_equity)).where(
            EquitySnapshot.account_id == account_id
        )
        result = await self.session.execute(stmt)
        peak = result.scalar()
        if peak is None or float(peak) <= 0:
            return None
        peak_val = float(peak)
        if current_equity > peak_val:
            return 0.0
        return (peak_val - current_equity) / peak_val

    async def _get_benchmark_return(self) -> Optional[float]:
        """获取 SPY 的当日收益率作为基准"""
        try:
            provider = MarketDataProvider()
            price = await provider.get_current_price("SPY")
            # 简化：返回 None，实际需要获取前一日收盘价对比
            return None
        except Exception:
            return None
