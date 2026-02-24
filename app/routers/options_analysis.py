"""V10: 期权分析路由（只读工具，不执行交易）"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.services.options_analysis_service import options_analysis_service

router = APIRouter(prefix="/options-analysis", tags=["V10-OptionsAnalysis"])


@router.get("/summary/{symbol}")
async def get_options_summary(
    symbol: str,
    current_user: str = Depends(get_current_user),
):
    """获取标的期权综合摘要（IV Rank + P/C Ratio + 异常大单）"""
    symbol = symbol.upper()
    try:
        return await options_analysis_service.get_summary(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Options analysis failed: {e}")


@router.get("/iv-surface/{symbol}")
async def get_iv_surface(
    symbol: str,
    current_user: str = Depends(get_current_user),
):
    """获取 IV 曲面数据（到期日 × 行权价 → IV）"""
    symbol = symbol.upper()
    try:
        return await options_analysis_service.get_iv_surface(symbol)
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
    try:
        return await options_analysis_service.get_iv_rank(symbol, lookback_days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IV rank failed: {e}")


@router.get("/unusual-activity/{symbol}")
async def get_unusual_activity(
    symbol: str,
    current_user: str = Depends(get_current_user),
):
    """检测期权异常大单（量/OI > 10x）"""
    symbol = symbol.upper()
    try:
        return {"symbol": symbol, "unusual": await options_analysis_service.get_unusual_activity(symbol)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unusual activity detection failed: {e}")
