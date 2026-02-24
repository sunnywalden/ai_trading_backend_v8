"""V10: 投资组合优化路由"""
from datetime import datetime
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
    risk_free_rate: float = 0.04
    current_weights: Optional[Dict[str, float]] = None


@router.get("/latest")
async def get_latest_snapshot(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取最新组合优化快照"""
    from sqlalchemy import text

    try:
        result = await session.execute(
            text(
                "SELECT method, target_weights as weights, frontier_data as frontier, "
                "expected_return, expected_volatility as volatility, sharpe_ratio as sharpe, created_at "
                "FROM portfolio_snapshots WHERE account_id=:aid ORDER BY created_at DESC LIMIT 1"
            ),
            {"aid": current_user},
        )
        row = result.fetchone()
        if not row:
            return {}  # V10: Return empty object instead of null to avoid client-side or middleware issues
        
        data = dict(row._mapping)
        return {
            "method": data["method"],
            "weights": data["weights"],
            "frontier": data["frontier"],
            "metrics": {
                "expected_return": float(data["expected_return"]) if data["expected_return"] else 0,
                "volatility": float(data["volatility"]) if data["volatility"] else 0,
                "sharpe": float(data["sharpe"]) if data["sharpe"] else 0,
            },
            "created_at": data["created_at"].isoformat() if data["created_at"] else None
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to fetch portfolio snapshot: {e}")
        # If table missing or query fails, return empty instead of 404/500 to keep UI stable
        return {}


@router.post("/optimize")
async def optimize_portfolio(
    body: OptimizeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """
    触发组合优化计算并存至快照库
    """
    try:
        from app.models.portfolio_snapshot import PortfolioSnapshot

        # 1. 核心优化计算 (Call scipy-based optimizer)
        result = await portfolio_optimizer.optimize(
            symbols=body.symbols,
            method=body.method,
            lookback_days=body.lookback_days,
            current_weights=body.current_weights,
            risk_free_rate=body.risk_free_rate,
        )

        # 2. 持久化到 MySQL
        new_snapshot = PortfolioSnapshot(
            account_id=current_user,
            method=body.method,
            current_weights=body.current_weights or {s: 0.0 for s in body.symbols},
            target_weights=result["target_weights"],
            frontier_data=result.get("frontier_data"),
            expected_return=result.get("expected_return"),
            expected_volatility=result.get("expected_volatility"),
            sharpe_ratio=result.get("sharpe_ratio"),
        )
        session.add(new_snapshot)
        await session.commit()

        # 3. 返回前端
        return {
            "status": "success",
            "weights": result["target_weights"],
            "metrics": {
                "expected_return": result.get("expected_return"),
                "volatility": result.get("expected_volatility"),
                "sharpe": result.get("sharpe_ratio"),
            },
            "frontier": result.get("frontier_data"),
        }
    except Exception as e:
        await session.rollback()
        # V10: Check for data related errors or scipy missing
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Portfolio optimization failed: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Optimization failed: {str(e)}"
        )    