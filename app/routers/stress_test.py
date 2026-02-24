"""V10: 压力测试路由"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.services.stress_test_service import stress_test_service

router = APIRouter(prefix="/stress-test", tags=["V10-StressTest"])


class StressTestRequest(BaseModel):
    positions: Dict[str, dict]  # {symbol: {"qty": float, "price": float, "market_value": float}}
    portfolio_equity: float
    scenarios: Optional[List[str]] = None  # None = 全部情景


@router.post("/run")
async def run_stress_test(
    body: StressTestRequest,
    current_user: str = Depends(get_current_user),
):
    """对当前持仓运行历史情景压力测试"""
    if body.portfolio_equity <= 0:
        raise HTTPException(status_code=400, detail="portfolio_equity 必须大于 0")

    result = await stress_test_service.run_scenarios(
        positions=body.positions,
        portfolio_equity=body.portfolio_equity,
        scenario_names=body.scenarios,
    )
    return result


@router.get("/scenarios")
async def get_available_scenarios(current_user: str = Depends(get_current_user)):
    """获取可用的压力测试情景列表"""
    return {"scenarios": stress_test_service.get_available_scenarios()}
