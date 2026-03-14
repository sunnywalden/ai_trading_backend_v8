"""
order_book_workbench read model — V11.1.1

Composes the open-order summary and recent order rows for the workbench
execution panel.  No business logic, no writes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.order_book_service import order_book_service


async def get_order_book_workbench(
    db: AsyncSession,
) -> dict[str, Any]:
    """Return composed order book data for the workbench read layer."""
    summary = await order_book_service.get_summary(db)
    orders_result = await order_book_service.list_orders(db)

    return {
        "summary": summary,
        "orders": orders_result,
    }
