"""V10: 期权分析路由（只读工具，不执行交易）"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.cache import cache
from app.core.config import settings
from app.services.options_analysis_service import options_analysis_service, _deep_clean

router = APIRouter(prefix="/options-analysis", tags=["V10-OptionsAnalysis"])


@router.get("/summary/{symbol}")
async def get_options_summary(
    symbol: str,
    current_user: str = Depends(get_current_user),
):
    """获取标的期权综合摘要（IV Rank + P/C Ratio + 异常大单）"""
    symbol = symbol.upper()
    cache_key = f"options:summary:{symbol}"
    
    # 尝试读取缓存
    cached = await cache.get(cache_key)
    if cached:
        cleaned = _deep_clean(cached)
        if cleaned != cached:
            await cache.set(cache_key, cleaned, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return cleaned

    try:
        result = await options_analysis_service.get_summary(symbol)
        result = _deep_clean(result)
        # 写入缓存
        await cache.set(cache_key, result, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Options analysis failed: {e}")


@router.get("/iv-surface/{symbol}")
async def get_iv_surface(
    symbol: str,
    current_user: str = Depends(get_current_user),
):
    """获取 IV 曲面数据（到期日 × 行权价 → IV）"""
    symbol = symbol.upper()
    cache_key = f"options:iv_surface:{symbol}"
    
    cached = await cache.get(cache_key)
    if cached:
        cleaned = _deep_clean(cached)
        if cleaned != cached:
            await cache.set(cache_key, cleaned, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return cleaned

    try:
        result = await options_analysis_service.get_iv_surface(symbol)
        result = _deep_clean(result)
        await cache.set(cache_key, result, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IV surface failed: {e}")


@router.get("/iv-rank/{symbol}")
async def get_iv_rank(
    symbol: str,
    lookback_days: int = 252,
    current_user: str = Depends(get_current_user),
):
    """计算 IV Rank（当前 IV 在 52 周区间中的百分位）"""
    symbol = symbol.upper()
    cache_key = f"options:iv_rank:{symbol}:{lookback_days}"
    
    cached = await cache.get(cache_key)
    if cached:
        cleaned = _deep_clean(cached)
        if cleaned != cached:
            await cache.set(cache_key, cleaned, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return cleaned

    try:
        result = await options_analysis_service.get_iv_rank(symbol, lookback_days)
        result = _deep_clean(result)
        await cache.set(cache_key, result, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IV rank failed: {e}")


@router.get("/unusual-activity/{symbol}")
async def get_unusual_activity(
    symbol: str,
    current_user: str = Depends(get_current_user),
):
    """检测期权异常大单（量/OI > 10x）"""
    symbol = symbol.upper()
    cache_key = f"options:unusual_activity:{symbol}"
    
    cached = await cache.get(cache_key)
    if cached:
        cleaned = _deep_clean(cached)
        if cleaned != cached:
            await cache.set(cache_key, cleaned, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return cleaned

    try:
        unusual = await options_analysis_service.get_unusual_activity(symbol)
        result = _deep_clean({"symbol": symbol, "unusual": unusual})
        await cache.set(cache_key, result, expire=settings.OPTIONS_ANALYSIS_CACHE_EXPIRE_HOURS * 3600)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unusual activity detection failed: {e}")
