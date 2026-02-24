"""V10: 投资组合优化路由"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.engine.portfolio.optimizer import portfolio_optimizer
from app.models.db import get_session

router = APIRouter(prefix="/portfolio", tags=["V10-Portfolio"])


class OptimizeRequest(BaseModel):
    symbols: List[str]
    method: str = "MARKOWITZ"  # MARKOWITZ / RISK_PARITY / KELLY
    lookback_days: int = 252
    current_weights: Optional[Dict[str, float]] = None


@router.post("/optimize")
async def optimize_portfolio(
    body: OptimizeRequest,
    current_user: str = Depends(get_current_user),
):
    """运行组合优化并返回有效前沿 + 推荐权重"""
    if len(body.symbols) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 个标的")
    if body.method not in ("MARKOWITZ", "RISK_PARITY", "KELLY"):
        raise HTTPException(status_code=400, detail="method 必须是 MARKOWITZ / RISK_PARITY / KELLY")

    try:
        result = await portfolio_optimizer.optimize(
            symbols=body.symbols,
            method=body.method,
            lookback_days=body.lookback_days,
            current_weights=body.current_weights,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化失败: {e}")

    # 持久化快照
    # TODO: 保存到 portfolio_snapshots 表

    return result


@router.get("/latest")
async def get_latest_snapshot(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取最新组合优化快照"""
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT * FROM portfolio_snapshots WHERE account_id=:aid ORDER BY created_at DESC LIMIT 1"
        ),
        {"aid": current_user},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No portfolio snapshot found")
    return dict(row._mapping)
