"""V9: 订单执行服务"""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Protocol
from uuid import uuid4
import logging

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.trade_pnl_attribution import TradePnlAttribution
from app.schemas.orders import OrderView
from app.broker.factory import make_option_broker_client

logger = logging.getLogger(__name__)


class OrderExecutor(Protocol):
    async def submit_order(self, order: dict) -> dict: ...
    async def cancel_order(self, order_id: str) -> bool: ...
    async def get_order_status(self, order_id: str) -> dict: ...


class PaperOrderExecutor:
    """模拟盘执行器：记录订单、按市场价模拟成交"""

    def __init__(self):
        self._orders: dict[str, dict] = {}

    async def submit_order(self, order: dict) -> dict:
        order_id = str(uuid4())
        from app.providers.market_data_provider import MarketDataProvider
        provider = MarketDataProvider()

        try:
            current_price = await provider.get_current_price(order["symbol"])
        except Exception:
            current_price = order.get("limit_price", 0.0)

        filled_price = current_price or order.get("limit_price", 0.0)

        order_record = {
            "order_id": order_id,
            "symbol": order["symbol"],
            "direction": order["direction"],
            "quantity": order["quantity"],
            "order_type": order.get("order_type", "MARKET"),
            "limit_price": order.get("limit_price"),
            "status": "FILLED",
            "filled_quantity": order["quantity"],
            "filled_price": filled_price,
            "plan_id": order.get("plan_id"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        self._orders[order_id] = order_record
        logger.info(f" 模拟成交: {order['direction']} {order['quantity']} {order['symbol']} @ ${filled_price:.2f}")
        return order_record

    async def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if not order or order["status"] != "PENDING":
            return False
        order["status"] = "CANCELLED"
        return True

    async def get_order_status(self, order_id: str) -> dict:
        return self._orders.get(order_id, {"status": "NOT_FOUND"})


class TigerOrderExecutor:
    """Tiger OpenAPI 真实下单执行器"""

    async def submit_order(self, order: dict) -> dict:
        # TODO: 接入 Tiger OpenAPI 下单
        raise NotImplementedError("Tiger real order execution not yet implemented. Use PAPER mode.")

    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("Tiger order cancellation not yet implemented.")

    async def get_order_status(self, order_id: str) -> dict:
        raise NotImplementedError("Tiger order status not yet implemented.")


class OrderSafetyGuard:
    """订单安全守卫"""

    def __init__(self, session: AsyncSession, account_id: str):
        self.session = session
        self.account_id = account_id

    async def check(self, order: dict, equity: float) -> tuple[bool, str]:
        """检查订单是否安全"""
        # 1. Fat Finger Guard: 单笔不超过净值 20%
        max_pct = getattr(settings, 'MAX_SINGLE_ORDER_PCT', 0.2)
        order_value = order["quantity"] * (order.get("limit_price", 0) or 100)
        if equity > 0 and order_value / equity > max_pct:
            return False, f"单笔订单金额 ${order_value:.0f} 超过净值 {max_pct*100:.0f}% 上限"

        # 2. 日亏损熔断
        max_daily_loss = getattr(settings, 'MAX_DAILY_LOSS_PCT', 0.05)
        daily_loss = await self._get_daily_loss()
        if equity > 0 and abs(daily_loss) / equity > max_daily_loss:
            return False, f"今日已亏损 {abs(daily_loss)/equity*100:.1f}%，触发日亏损熔断"

        # 3. 交易模式检查
        order_mode = getattr(settings, 'ORDER_MODE', 'PAPER')
        if order_mode == "OFF" or settings.TRADE_MODE == "OFF":
            return False, "交易模式为 OFF，禁止下单"

        return True, "ok"

    async def _get_daily_loss(self) -> float:
        """获取今日已实现亏损总额"""
        today = date.today()
        stmt = select(func.sum(TradePnlAttribution.realized_pnl)).where(
            and_(
                TradePnlAttribution.account_id == self.account_id,
                TradePnlAttribution.trade_date == today,
                TradePnlAttribution.realized_pnl < 0,
            )
        )
        result = await self.session.execute(stmt)
        return float(result.scalar() or 0)


class OrderService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._paper_executor = PaperOrderExecutor()

    def _get_executor(self) -> OrderExecutor:
        order_mode = getattr(settings, 'ORDER_MODE', 'PAPER')
        if order_mode == "REAL":
            return TigerOrderExecutor()
        return self._paper_executor

    async def submit_order(self, account_id: str, payload: dict) -> OrderView:
        """提交订单"""
        # 安全检查
        broker = make_option_broker_client()
        try:
            equity = float(await broker.get_equity())
        except Exception:
            equity = getattr(settings, 'DEFAULT_RISK_BUDGET_USD', 20000.0)

        guard = OrderSafetyGuard(self.session, account_id)
        is_safe, reason = await guard.check(payload, equity)
        if not is_safe:
            return OrderView(
                order_id="REJECTED",
                symbol=payload["symbol"],
                direction=payload["direction"],
                quantity=payload["quantity"],
                order_type=payload.get("order_type", "MARKET"),
                status="REJECTED",
                plan_id=payload.get("plan_id"),
            )

        executor = self._get_executor()
        result = await executor.submit_order(payload)

        # 记录 PnL 归因（如果是卖出且关联计划）
        if result.get("status") == "FILLED" and payload.get("direction") == "SELL":
            try:
                pnl_record = TradePnlAttribution(
                    account_id=account_id,
                    symbol=payload["symbol"],
                    trade_date=date.today(),
                    direction=payload["direction"],
                    entry_price=Decimal("0"),
                    exit_price=Decimal(str(result.get("filled_price", 0))),
                    quantity=Decimal(str(payload["quantity"])),
                    realized_pnl=Decimal("0"),
                    strategy_tag=payload.get("strategy_tag"),
                    plan_id=payload.get("plan_id"),
                )
                self.session.add(pnl_record)
                await self.session.commit()
            except Exception:
                pass

        return OrderView(
            order_id=result.get("order_id", ""),
            symbol=result.get("symbol", payload["symbol"]),
            direction=result.get("direction", payload["direction"]),
            quantity=result.get("quantity", payload["quantity"]),
            order_type=result.get("order_type", "MARKET"),
            limit_price=result.get("limit_price"),
            status=result.get("status", "UNKNOWN"),
            filled_quantity=result.get("filled_quantity", 0),
            filled_price=result.get("filled_price"),
            plan_id=result.get("plan_id"),
            created_at=result.get("created_at"),
            updated_at=result.get("updated_at"),
        )

    async def get_order_status(self, order_id: str) -> OrderView:
        executor = self._get_executor()
        result = await executor.get_order_status(order_id)
        return OrderView(
            order_id=result.get("order_id", order_id),
            symbol=result.get("symbol", ""),
            direction=result.get("direction", ""),
            quantity=result.get("quantity", 0),
            order_type=result.get("order_type", ""),
            status=result.get("status", "NOT_FOUND"),
            filled_quantity=result.get("filled_quantity", 0),
            filled_price=result.get("filled_price"),
        )

    async def cancel_order(self, order_id: str) -> bool:
        executor = self._get_executor()
        return await executor.cancel_order(order_id)
