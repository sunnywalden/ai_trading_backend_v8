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
    scenario_ids: Optional[List[str]] = None
    symbols: Optional[List[str]] = None
    use_current_positions: bool = True


@router.post("/run")
async def run_stress_test(
    body: StressTestRequest,
    current_user: str = Depends(get_current_user),
):
    """对持仓运行历史情景压力测试 (V10)"""
    # 模拟获取当前持仓 logic
    positions = {
        "AAPL": {"qty": 100, "price": 180, "market_value": 18000},
        "TSLA": {"qty": 50, "price": 240, "market_value": 12000},
    }
    portfolio_equity = 100000.0

    result = await stress_test_service.run_scenarios(
        positions=positions,
        portfolio_equity=portfolio_equity,
        scenario_ids=body.scenario_ids,
    )
    return result


@router.get("/scenarios")
async def get_available_scenarios(current_user: str = Depends(get_current_user)):
    """获取可用的压力测试情景列表"""
    return {"scenarios": stress_test_service.get_available_scenarios()}
