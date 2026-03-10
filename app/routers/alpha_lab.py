from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.v1051_research_service import v1051_research_service

router = APIRouter(prefix="/api/v1/alpha-lab", tags=["V10.5.3-AlphaTruth"])


async def _resolve_broker_account_id(current_user: str) -> str:
    with suppress(RuntimeError, ValueError, TypeError, AttributeError):
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            return str(broker_id)
    return str(current_user)


@router.get("/snapshot")
async def get_alpha_lab_snapshot(
    db: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[str, Depends(get_current_user)],
    lookback_days: Annotated[int, Query(ge=7, le=365)] = 90,
):
    account_id = await _resolve_broker_account_id(user_id)
    return await v1051_research_service.get_alpha_lab_snapshot(
        db,
        account_id,
        lookback_days=lookback_days,
    )
