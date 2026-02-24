"""V10: TwapVwapService — TWAP/VWAP 执行算法"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


class TwapVwapService:
    """
    TWAP：将总量平均分配到 N 个时间片，每隔 interval_secs 执行一片
    VWAP：按实时/历史成交量比例分配每片数量（简化：等权重）
    MKT：直接市价单
    """

    def __init__(self):
        # 内存任务注册表（补充 DB 持久化）
        self._tasks: Dict[str, dict] = {}

    async def submit(
        self,
        symbol: str,
        side: str,
        quantity: float,
        algo: str = "TWAP",
        duration_minutes: int = 30,
        slices: int = 6,
        source: str = "manual",
        account_id: str = "default",
        db: Optional[AsyncSession] = None,
    ) -> str:
        """注册算法执行任务，返回 task_id"""
        task_id = str(uuid.uuid4())
        interval_secs = int(duration_minutes * 60 / max(slices, 1))

        task_record = {
            "task_id": task_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "algo": algo,
            "slices": slices,
            "duration_minutes": duration_minutes,
            "interval_secs": interval_secs,
            "source": source,
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "slices_log": [],
        }
        self._tasks[task_id] = task_record

        try:
            from app.models.algo_execution_task import AlgoExecutionTask
            if db:
                task_obj = AlgoExecutionTask(
                    account_id=account_id,
                    symbol=symbol,
                    side=side,
                    algo=algo,
                    total_qty=quantity,
                    slices=slices,
                    interval_secs=interval_secs,
                    status="PENDING",
                )
                db.add(task_obj)
                await db.commit()
        except Exception:
            pass

        logger.info(f"[TwapVwap] Submitted {task_id}: {algo} {side} {symbol} qty={quantity}")

        if algo == "MKT":
            asyncio.create_task(self._execute_mkt(task_id, account_id, symbol, side, quantity))
        else:
            asyncio.create_task(
                self._execute_sliced(task_id, account_id, symbol, side, quantity, algo, slices, interval_secs)
            )
        return task_id

    async def list_tasks(self, status: Optional[str] = None, limit: int = 20) -> List[dict]:
        """列出任务（内存）"""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t["status"] == status.upper()]
        tasks.sort(key=lambda t: t["created_at"], reverse=True)
        return tasks[:limit]

    async def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务详情"""
        return self._tasks.get(task_id)

    async def cancel(self, task_id: str) -> bool:
        """取消 PENDING 任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task["status"] != "PENDING":
            return False
        task["status"] = "CANCELLED"
        logger.info(f"[TwapVwap] Task {task_id} cancelled")
        return True

    async def _execute_mkt(
        self, task_id: str, account_id: str, symbol: str, side: str, qty: float
    ) -> None:
        """直接市价单执行"""
        self._tasks[task_id]["status"] = "RUNNING"
        logger.info(f"[TwapVwap] MKT {side} {symbol} qty={qty}")
        try:
            from app.services.order_service import OrderService
            result = await OrderService().submit_order(account_id, symbol, side, qty, "MKT")
            self._tasks[task_id]["status"] = "DONE"
            logger.info(f"[TwapVwap] MKT executed: {result}")
        except Exception as e:
            self._tasks[task_id]["status"] = "FAILED"
            logger.error(f"[TwapVwap] MKT failed: {e}")

    async def _execute_sliced(
        self,
        task_id: str,
        account_id: str,
        symbol: str,
        side: str,
        total_qty: float,
        algo: str,
        slices: int,
        interval_secs: int,
    ) -> None:
        """切片执行（TWAP / VWAP）"""
        task = self._tasks.get(task_id, {})
        if task.get("status") == "CANCELLED":
            return
        task["status"] = "RUNNING"
        slice_qty = total_qty / slices
        filled_qty = 0.0

        for i in range(slices):
            # 检查是否被取消
            if self._tasks.get(task_id, {}).get("status") == "CANCELLED":
                logger.info(f"[TwapVwap] Task {task_id} cancelled mid-execution at slice {i+1}")
                break
            try:
                from app.services.order_service import OrderService
                result = await OrderService().submit_order(
                    account_id, symbol, side, slice_qty, "MKT"
                )
                filled_price = result.get("filled_price", 0.0)
                filled_qty += slice_qty
                log_entry = {
                    "slice": i + 1,
                    "qty": slice_qty,
                    "price": filled_price,
                    "filled_at": datetime.now(timezone.utc).isoformat(),
                }
                if task_id in self._tasks:
                    self._tasks[task_id].setdefault("slices_log", []).append(log_entry)
                logger.info(f"[TwapVwap] {algo} slice {i+1}/{slices} {side} {symbol} qty={slice_qty:.2f} @ {filled_price}")
            except Exception as e:
                logger.error(f"[TwapVwap] Slice {i+1} failed: {e}")
                if task_id in self._tasks:
                    self._tasks[task_id].setdefault("slices_log", []).append({"slice": i + 1, "error": str(e)})

            if i < slices - 1:
                await asyncio.sleep(interval_secs)

        if task_id in self._tasks and self._tasks[task_id]["status"] == "RUNNING":
            self._tasks[task_id]["status"] = "DONE"
        logger.info(f"[TwapVwap] Task {task_id} complete. filled={filled_qty}/{total_qty}")


# 全局单例
twap_vwap_service = TwapVwapService()
