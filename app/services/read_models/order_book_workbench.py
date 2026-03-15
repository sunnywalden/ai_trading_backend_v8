"""
order_book_workbench read model — V11.1.1

Composes the open-order summary and recent order rows for the workbench
execution panel.  No business logic, no writes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.order_book import OrderBookFilter
from app.services.order_book_service import order_book_service


async def get_order_book_workbench(
    db: AsyncSession,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Return composed order book data for the workbench read layer."""
    summary = await order_book_service.get_summary_for_account(db, account_id)
    filters = None
    if account_id is not None:
        filters = OrderBookFilter(account_id=account_id)
    orders_result = await order_book_service.list_orders(db, filters)

    return {
        "summary": summary,
        "orders": orders_result,
    }
