from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict, Any, Optional, Callable
from app.i18n import get_translator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.services.market_hotspot_service import MarketHotspotService

router = APIRouter(prefix="/hotspots", tags=["Market Hotspots"])

@router.get("/latest")
async def get_latest_hotspots(
    force_refresh: bool = Query(False, description="是否强制从源刷新"),
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """
    获取最新的市场热点（资讯、宏观数据、重大动态等）
    """
    try:
        service = MarketHotspotService(session)
        hotspots = await service.get_latest_hotspots(force_refresh=force_refresh)
        return hotspots
    except Exception as e:
        raise HTTPException(status_code=500, detail=t("error.fetch_hotspots_failed", error=str(e)))

@router.get("/categories")
async def get_categories():
    """
    获取热点分类列表
    """
    from app.services.market_hotspot_service import HotspotCategory
    return [
        {"id": cat.value, "label": cat.name} for cat in HotspotCategory
    ]
