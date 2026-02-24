"""V10: 算法执行路由（TWAP / VWAP / MKT）"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.services.twap_vwap_service import twap_vwap_service

router = APIRouter(prefix="/execution-algo", tags=["V10-ExecAlgo"])


class AlgoSubmitRequest(BaseModel):
    symbol: str
    side: str               # BUY / SELL
    quantity: float
    algo: str = "TWAP"      # TWAP / VWAP / MKT
    duration_minutes: int = 30
    slices: int = 6
    source: Optional[str] = "manual"   # manual / autonomous


@router.post("/submit")
async def submit_algo_order(
    req: AlgoSubmitRequest,
    current_user: str = Depends(get_current_user),
):
    """提交算法执行任务"""
    try:
        task_id = await twap_vwap_service.submit(
            symbol=req.symbol.upper(),
            side=req.side.upper(),
            quantity=req.quantity,
            algo=req.algo.upper(),
            duration_minutes=req.duration_minutes,
            slices=req.slices,
            source=req.source or "manual",
        )
        return {"task_id": task_id, "status": "PENDING"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Submit failed: {e}")


@router.get("/tasks")
async def list_algo_tasks(
    status: Optional[str] = None,
    limit: int = 20,
    current_user: str = Depends(get_current_user),
):
    """列出算法执行任务"""
    try:
        tasks = await twap_vwap_service.list_tasks(status=status, limit=limit)
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List tasks failed: {e}")


@router.get("/tasks/{task_id}")
async def get_algo_task(
    task_id: str,
    current_user: str = Depends(get_current_user),
):
    """获取算法任务详情"""
    try:
        task = await twap_vwap_service.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Get task failed: {e}")


@router.delete("/tasks/{task_id}")
async def cancel_algo_task(
    task_id: str,
    current_user: str = Depends(get_current_user),
):
    """取消算法执行任务（仅对 PENDING 有效）"""
    try:
        ok = await twap_vwap_service.cancel(task_id)
        if not ok:
            raise HTTPException(status_code=409, detail="Task cannot be cancelled")
        return {"task_id": task_id, "status": "CANCELLED"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cancel failed: {e}")
