"""V9: 价格告警服务"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.price_alert import PriceAlert, AlertHistory
from app.providers.market_data_provider import MarketDataProvider


class AlertService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_alert(self, account_id: str, payload: dict) -> PriceAlert:
        """创建价格告警规则"""
        alert = PriceAlert(account_id=account_id, **payload)
        self.session.add(alert)
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def update_alert(self, alert_id: int, account_id: str, payload: dict) -> Optional[PriceAlert]:
        """更新告警规则"""
        alert = await self._get_by_id(alert_id, account_id)
        if not alert:
            return None
        for key, value in payload.items():
            if value is not None and hasattr(alert, key):
                setattr(alert, key, value)
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def delete_alert(self, alert_id: int, account_id: str) -> bool:
        """删除告警规则"""
        alert = await self._get_by_id(alert_id, account_id)
        if not alert:
            return False
        await self.session.delete(alert)
        await self.session.commit()
        return True

    async def list_alerts(self, account_id: str, status: Optional[str] = None) -> list[PriceAlert]:
        """查询告警列表"""
        stmt = select(PriceAlert).where(PriceAlert.account_id == account_id)
        if status:
            stmt = stmt.where(PriceAlert.alert_status == status)
        stmt = stmt.order_by(desc(PriceAlert.created_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_history(self, account_id: str, limit: int = 20) -> list[AlertHistory]:
        """查询告警触发历史"""
        stmt = select(AlertHistory).where(
            AlertHistory.account_id == account_id
        ).order_by(desc(AlertHistory.trigger_time)).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def check_alerts(self, account_id: str) -> list[dict]:
        """检查并触发告警（由定时任务调用）"""
        active_alerts = await self.list_alerts(account_id, status="ACTIVE")
        if not active_alerts:
            return []

        provider = MarketDataProvider()
        triggered = []

        # 按 symbol 分组获取价格
        symbols = list(set(a.symbol for a in active_alerts))
        prices = {}
        for sym in symbols:
            try:
                prices[sym] = await provider.get_current_price(sym)
            except Exception:
                pass

        for alert in active_alerts:
            current_price = prices.get(alert.symbol)
            if current_price is None:
                continue

            threshold = float(alert.threshold)
            should_trigger = False

            if alert.condition_type == "price_above" and current_price >= threshold:
                should_trigger = True
            elif alert.condition_type == "price_below" and current_price <= threshold:
                should_trigger = True
            elif alert.condition_type == "pct_change":
                # 简化：暂不实现百分比变化检测
                pass

            if should_trigger:
                await self._trigger_alert(alert, current_price)
                triggered.append({
                    "alert_id": alert.id,
                    "symbol": alert.symbol,
                    "trigger_price": current_price,
                    "condition": alert.condition_type,
                    "action": alert.action,
                })

        return triggered

    async def _trigger_alert(self, alert: PriceAlert, trigger_price: float):
        """触发告警"""
        now = datetime.utcnow()

        # 更新告警状态
        alert.alert_status = "TRIGGERED"
        alert.triggered_at = now

        # 记录历史
        history = AlertHistory(
            alert_id=alert.id,
            account_id=alert.account_id,
            symbol=alert.symbol,
            trigger_price=trigger_price,
            trigger_time=now,
            notification_sent=True,
            action_taken=alert.action,
        )
        self.session.add(history)
        await self.session.commit()

    async def _get_by_id(self, alert_id: int, account_id: str) -> Optional[PriceAlert]:
        stmt = select(PriceAlert).where(
            and_(PriceAlert.id == alert_id, PriceAlert.account_id == account_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
