"""V10: 回测中心路由"""
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.engine.backtest.runner import backtest_runner
from app.models.backtest_task import BacktestTask
from app.models.db import get_session

router = APIRouter(prefix="/backtest", tags=["V10-Backtest"])


class BacktestRunRequest(BaseModel):
    strategy_type: str  # V10 ALIGNMENT
    symbols: List[str]
    start_date: date
    end_date: date
    initial_capital: float = 100000.0
    walk_forward: bool = False
    params: Optional[Dict[str, Any]] = None


@router.post("/run")
async def run_backtest(
    body: BacktestRunRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """提交回测任务（同步执行，小数据集；大数据集建议用后台任务）"""

    task = BacktestTask(
        account_id=current_user,
        strategy_name=body.strategy_type,
        symbols=body.symbols,
        start_date=body.start_date,
        end_date=body.end_date,
        initial_capital=body.initial_capital,
        walk_forward=body.walk_forward,
        status="RUNNING",
    )
    session.add(task)
    await session.flush()
    task_id = task.id

    try:
        result = await backtest_runner.run(
            strategy_name=body.strategy_type,
            symbols=body.symbols,
            start=body.start_date,
            end=body.end_date,
            initial_capital=body.initial_capital,
            walk_forward=body.walk_forward,
        )
        task.status = "DONE"
        task.result = result
        task.completed_at = datetime.now(timezone.utc)
    except Exception as e:
        task.status = "FAILED"
        task.error_msg = str(e)
        await session.commit()
        raise HTTPException(status_code=500, detail=f"Backtest failed: {e}")

    await session.commit()
    return {"task_id": task_id, "status": "DONE", "result": result}


@router.get("/tasks")
async def list_tasks(
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取回测任务列表"""
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT id, strategy_name, symbols, status, result, created_at "
            "FROM backtest_tasks WHERE account_id=:aid ORDER BY created_at DESC LIMIT :lim"
        ),
        {"aid": current_user, "lim": limit},
    )
    rows = result.fetchall()
    import json
    
    return {
        "tasks": [
            {
                "id": r[0],
                "strategy_type": r[1],  # V10 FE Alignment
                "symbols": json.loads(r[2]) if isinstance(r[2], str) else r[2],
                "status": r[3],
                "result": json.loads(r[4]) if isinstance(r[4], str) else r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    }


@router.get("/tasks/{task_id}/report")
async def get_task_report(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """获取回测报告"""
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT * FROM backtest_tasks WHERE id=:id AND account_id=:aid"),
        {"id": task_id, "aid": current_user},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    
    import json
    data = dict(row._mapping)
    # V10: Ensure JSON fields are parsed for the frontend report view
    if isinstance(data.get("result"), str):
        try:
            data["result"] = json.loads(data["result"])
        except:
            pass
    if isinstance(data.get("symbols"), str):
        try:
            data["symbols"] = json.loads(data["symbols"])
        except:
            pass
            
    return data
