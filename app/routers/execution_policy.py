from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.execution_policy_service import execution_policy_service

router = APIRouter(
    prefix="/api/v1/execution-policy",
    tags=["V10.5.1-ExecutionPolicy"],
)


async def _resolve_broker_account_id(current_user: str) -> str:
    with suppress(RuntimeError, ValueError, TypeError, AttributeError):
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            return str(broker_id)
    return str(current_user)


@router.get("/overview")
async def get_execution_policy_overview(
    db: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[str, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=5, le=100)] = 20,
    symbol: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    order_id: Annotated[
        str | None,
        Query(alias="orderId"),
    ] = None,
):
    account_id = await _resolve_broker_account_id(user_id)
    return await execution_policy_service.get_policy_overview(
        db,
        account_id,
        limit=limit,
        symbol=symbol,
        action=action,
        order_id=order_id,
    )


@router.get(
    "/intents/{intent_id}",
    responses={404: {"description": "Execution intent not found"}},
)
async def get_execution_policy_detail(
    intent_id: int,
    db: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[str, Depends(get_current_user)],
):
    account_id = await _resolve_broker_account_id(user_id)
    detail = await execution_policy_service.get_policy_detail(
        db,
        account_id,
        intent_id,
    )
    if detail is None:
        raise HTTPException(
            status_code=404, detail=f"Execution intent {intent_id} not found"
        )
    return detail
