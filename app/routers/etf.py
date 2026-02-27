from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models.db import get_session
from app.models.etf_watchlist import EtfWatchlist
from app.providers.market_data_provider import market_data_provider
from pydantic import BaseModel
from typing import List, Optional
import logging

router = APIRouter(prefix="/etf", tags=["ETF Watchlist"])
logger = logging.getLogger(__name__)

class EtfWatchlistCreate(BaseModel):
    symbol: str

@router.get("/watchlist")
async def get_etf_watchlist(session: AsyncSession = Depends(get_session)):
    stmt = select(EtfWatchlist)
    result = await session.execute(stmt)
    items = result.scalars().all()

    if not items:
        return {"items": []}

    # 一次 Tiger API 调用批量获取所有 ETF 价格（避免逐个请求触发限流）
    symbols = [item.symbol for item in items]
    try:
        prices = await market_data_provider.get_prices_batch(symbols)
    except Exception as e:
        logger.warning(f"[ETF] Batch price fetch failed: {e}")
        prices = {}

    resp_items = []
    for item in items:
        price = prices.get(item.symbol, 0.0) or 0.0
        resp_items.append({
            "symbol": item.symbol,
            "name": item.name or item.symbol,
            "price": price,
            "change_pct": 0.0,
            "category": item.category or "ETF",
            "market": item.market or ("HK" if item.symbol.isdigit() else "US"),
        })

    return {"items": resp_items}

@router.post("/watchlist")
async def add_to_watchlist(data: EtfWatchlistCreate, session: AsyncSession = Depends(get_session)):
    sym = data.symbol.strip().upper()
    # Check if already exists
    stmt = select(EtfWatchlist).where(EtfWatchlist.symbol == sym)
    result = await session.execute(stmt)
    if result.scalars().first():
        return {"status": "already_exists"}
    
    # Simple logic to infer market
    market = "HK" if sym.isdigit() else "US"
    
    new_item = EtfWatchlist(symbol=sym, market=market)
    session.add(new_item)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
        
    return {"status": "ok"}

@router.delete("/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str, session: AsyncSession = Depends(get_session)):
    stmt = delete(EtfWatchlist).where(EtfWatchlist.symbol == symbol.upper())
    await session.execute(stmt)
    await session.commit()
    return {"status": "ok"}
