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
    from sqlalchemy import select
    from app.models.portfolio_snapshot import PortfolioSnapshot

    try:
        # 使用 ORM select 确保 JSON 类型被正确处理
        stmt = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id == current_user)
            .order_by(PortfolioSnapshot.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        snapshot = result.scalar_one_or_none()
        
        if not snapshot:
            return {}  # V10: Return empty object instead of null
        
        # 确保 JSON 字段是解解析后的对象
        import json
        def ensure_obj(val):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except:
                    return val
            return val

        return {
            "method": snapshot.method,
            "weights": ensure_obj(snapshot.target_weights),
            "frontier": ensure_obj(snapshot.frontier_data),
            "metrics": {
                "expected_return": float(snapshot.expected_return) if snapshot.expected_return else 0,
                "volatility": float(snapshot.expected_volatility) if snapshot.expected_volatility else 0,
                "sharpe": float(snapshot.sharpe_ratio) if snapshot.sharpe_ratio else 0,
            },
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to fetch portfolio snapshot: {e}")
        return {}


@router.get("/history")
async def get_snapshot_history(
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取组合优化历史快照列表"""
    from sqlalchemy import select
    from app.models.portfolio_snapshot import PortfolioSnapshot
    import json

    def ensure_obj(val):
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return val
        return val

    try:
        stmt = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id == current_user)
            .order_by(PortfolioSnapshot.created_at.desc())
            .limit(min(limit, 50))
        )
        result = await session.execute(stmt)
        snapshots = result.scalars().all()
        return [
            {
                "id": s.id,
                "method": s.method,
                "weights": ensure_obj(s.target_weights),
                "metrics": {
                    "expected_return": float(s.expected_return) if s.expected_return else 0,
                    "volatility": float(s.expected_volatility) if s.expected_volatility else 0,
                    "sharpe": float(s.sharpe_ratio) if s.sharpe_ratio else 0,
                },
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snapshots
        ]
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to fetch portfolio history: {e}")
        return []


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