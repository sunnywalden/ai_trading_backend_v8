from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.factory import make_option_broker_client
from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.v1051_research_service import v1051_research_service

router = APIRouter(prefix="/api/v1/governance", tags=["V10.5.1-Governance"])


async def _resolve_broker_account_id(current_user: str) -> str:
    try:
        broker = make_option_broker_client()
        broker_id = await broker.get_account_id()
        if broker_id:
            return str(broker_id)
    except Exception:
        pass
    return str(current_user)


@router.get("/pipeline")
async def get_governance_pipeline(
    limit: int = Query(default=20, ge=5, le=100),
    db: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user),
):
    account_id = await _resolve_broker_account_id(user_id)
    return await v1051_research_service.get_governance_pipeline_snapshot(
        db,
        account_id,
        limit=limit,
    )