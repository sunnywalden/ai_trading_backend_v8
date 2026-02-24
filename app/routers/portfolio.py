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


@router.post("/optimize")
async def optimize_portfolio(
    body: OptimizeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """运行组合优化并返回有效前沿 + 推荐权重"""
    if len(body.symbols) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 个标的")
    if body.method not in ("MARKOWITZ", "RISK_PARITY", "KELLY"):
        raise HTTPException(status_code=400, detail="method 必须是 MARKOWITZ / RISK_PARITY / KELLY")

    try:
        raw_result = await portfolio_optimizer.optimize(
            symbols=body.symbols,
            method=body.method,
            lookback_days=body.lookback_days,
            current_weights=body.current_weights,
            risk_free_rate=body.risk_free_rate,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化失败: {e}")

    # 统一命名格式以匹配前端
    result = {
        "method": raw_result["method"],
        "weights": raw_result["target_weights"],
        "metrics": {
            "expected_return": raw_result["expected_return"],
            "volatility": raw_result["expected_volatility"],
            "sharpe": raw_result["sharpe_ratio"],
        },
        "frontier": raw_result["frontier_data"],
        "created_at": datetime.now().isoformat()
    }

    # 持久化快照 (V10)
    try:
        from app.models.portfolio_snapshot import PortfolioSnapshot
        snapshot = PortfolioSnapshot(
            account_id=current_user,
            method=body.method,
            current_weights=body.current_weights or {},
            target_weights=raw_result["target_weights"],
            frontier_data=raw_result["frontier_data"],
            expected_return=raw_result["expected_return"],
            expected_volatility=raw_result["expected_volatility"],
            sharpe_ratio=raw_result["sharpe_ratio"],
        )
        session.add(snapshot)
        await session.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to save portfolio snapshot: {e}")

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
            "SELECT method, target_weights as weights, frontier_data as frontier, "
            "expected_return, expected_volatility as volatility, sharpe_ratio as sharpe, created_at "
            "FROM portfolio_snapshots WHERE account_id=:aid ORDER BY created_at DESC LIMIT 1"
        ),
        {"aid": current_user},
    )
    row = result.fetchone()
    if not row:
        return None  # 返回 null，前端 v-if="result" 会处理
    
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
