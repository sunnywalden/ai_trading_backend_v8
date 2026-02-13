from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.services.market_hotspot_service import MarketHotspotService

router = APIRouter(prefix="/hotspots", tags=["Market Hotspots"])

@router.get("/latest")
async def get_latest_hotspots(
    force_refresh: bool = Query(False, description="是否强制从源刷新"),
    session: AsyncSession = Depends(get_session)
):
    """
    获取最新的市场热点（资讯、宏观数据、重大动态等）
    """
    try:
        service = MarketHotspotService(session)
        hotspots = await service.get_latest_hotspots(force_refresh=force_refresh)
        return hotspots
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch market hotspots: {str(e)}")

@router.get("/categories")
async def get_categories():
    """
    获取热点分类列表
    """
    from app.services.market_hotspot_service import HotspotCategory
    return [
        {"id": cat.value, "label": cat.name} for cat in HotspotCategory
    ]
