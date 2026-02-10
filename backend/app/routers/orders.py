"""V9: 订单执行路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.broker.factory import make_option_broker_client
from app.services.order_service import OrderService
from app.schemas.orders import OrderSubmitRequest, OrderSubmitResponse, OrderStatusResponse, OrderView

router = APIRouter(prefix="/orders", tags=["V9-Orders"])


@router.post("/submit", response_model=OrderSubmitResponse)
async def submit_order(
    payload: OrderSubmitRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """提交订单（Paper / Real）"""
    broker = make_option_broker_client()
    account_id = await broker.get_account_id()
    svc = OrderService(session)
    order_view = await svc.submit_order(account_id, payload.model_dump(exclude_none=True))
    return OrderSubmitResponse(status="ok" if order_view.status != "REJECTED" else "rejected", order=order_view)


@router.get("/{order_id}/status", response_model=OrderStatusResponse)
async def get_order_status(
    order_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """查询订单状态"""
    svc = OrderService(session)
    order_view = await svc.get_order_status(order_id)
    return OrderStatusResponse(order=order_view)


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """撤单"""
    svc = OrderService(session)
    ok = await svc.cancel_order(order_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot cancel order")
    return {"status": "ok", "order_id": order_id}
