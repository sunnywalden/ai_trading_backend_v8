"""V10: Paper Trading 路由"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.paper_trading_service import paper_trading_service

router = APIRouter(prefix="/paper-trading", tags=["V10-PaperTrading"])


class PaperTradeRequest(BaseModel):
    symbol: str
    side: str  # BUY / SELL
    quantity: float
    order_type: str = "MKT"
    limit_price: Optional[float] = None


class GraduationCheckRequest(BaseModel):
    strategy_name: str
    symbols: List[str]


@router.get("/status")
async def get_paper_status(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取模拟账户状态"""
    return await paper_trading_service.get_status(current_user, session)


@router.post("/trade")
async def execute_trade(
    body: PaperTradeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """执行模拟交易 (V10)"""
    if body.side.upper() not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side 必须是 BUY 或 SELL")
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity 必须大于 0")

    result = await paper_trading_service.execute_paper_trade(
        account_id=current_user,
        symbol=body.symbol,
        side=body.side,
        qty=body.quantity,
        price=body.limit_price or 0.0,  # 简化：如果是 MKT 价格可在 service 层处理
        db=session,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("reason", "Trade failed"))
    return result


@router.post("/check-graduation")
async def check_graduation(
    body: GraduationCheckRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """检查策略是否满足 Paper→Live 毕业条件"""
    return await paper_trading_service.check_graduation(
        account_id=current_user,
        strategy_name=body.strategy_name,
        symbols=body.symbols,
        db=session,
    )


@router.post("/reset")
async def reset_paper_account(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """重置模拟账户（清空持仓和交易记录）"""
    return await paper_trading_service.reset(current_user, session)
