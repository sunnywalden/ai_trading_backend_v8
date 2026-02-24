"""持仓评估任务配置 & 任务管理服务"""
import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position_eval_config import PositionEvalConfig
from app.models.position_eval_task import PositionEvalTask
from app.schemas.position_eval import (
    PositionEvalConfigCreate,
    PositionEvalConfigUpdate,
    TriggerEvalTaskRequest,
)

logger = logging.getLogger(__name__)


class PositionEvalService:
    """持仓评估任务服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ─────────────────────────────────────────
    # 配置管理
    # ─────────────────────────────────────────

    async def list_configs(self, account_id: str) -> List[PositionEvalConfig]:
        result = await self.session.execute(
            select(PositionEvalConfig)
            .where(PositionEvalConfig.account_id == account_id)
            .order_by(PositionEvalConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_config(self, account_id: str, config_id: int) -> Optional[PositionEvalConfig]:
        result = await self.session.execute(
            select(PositionEvalConfig).where(
                PositionEvalConfig.id == config_id,
                PositionEvalConfig.account_id == account_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_config(
        self, account_id: str, data: PositionEvalConfigCreate
    ) -> PositionEvalConfig:
        config = PositionEvalConfig(
            account_id=account_id,
            name=data.name,
            description=data.description,
            scope=data.scope.value,
            symbols=data.symbols,
            eval_dimensions=data.eval_dimensions,
            trigger_mode=data.trigger_mode.value,
            trigger_time=data.trigger_time,
            enabled=data.enabled,
            extra_params=data.extra_params,
        )
        self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def update_config(
        self, account_id: str, config_id: int, data: PositionEvalConfigUpdate
    ) -> Optional[PositionEvalConfig]:
        config = await self.get_config(account_id, config_id)
        if config is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            # scope / trigger_mode 需要取 .value（Enum → str）
            if hasattr(value, "value"):
                value = value.value
            setattr(config, field, value)
        config.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def delete_config(self, account_id: str, config_id: int) -> bool:
        config = await self.get_config(account_id, config_id)
        if config is None:
            return False
        await self.session.delete(config)
        await self.session.commit()
        return True

    # ─────────────────────────────────────────
    # 任务管理
    # ─────────────────────────────────────────

    async def list_pending_tasks(self, account_id: str) -> List[PositionEvalTask]:
        result = await self.session.execute(
            select(PositionEvalTask)
            .where(
                PositionEvalTask.account_id == account_id,
                PositionEvalTask.status == "PENDING",
            )
            .order_by(PositionEvalTask.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_history_tasks(
        self,
        account_id: str,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ):
        """已执行任务（DONE / FAILED / CANCELLED / RUNNING）"""
        conditions = [
            PositionEvalTask.account_id == account_id,
            PositionEvalTask.status != "PENDING",
        ]
        if status:
            conditions.append(PositionEvalTask.status == status)

        # count
        count_q = await self.session.execute(
            select(func.count()).select_from(PositionEvalTask).where(and_(*conditions))
        )
        total = count_q.scalar_one()

        # items
        offset = (page - 1) * page_size
        result = await self.session.execute(
            select(PositionEvalTask)
            .where(and_(*conditions))
            .order_by(PositionEvalTask.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = list(result.scalars().all())
        return total, items

    async def get_task(self, account_id: str, task_id: int) -> Optional[PositionEvalTask]:
        result = await self.session.execute(
            select(PositionEvalTask).where(
                PositionEvalTask.id == task_id,
                PositionEvalTask.account_id == account_id,
            )
        )
        return result.scalar_one_or_none()

    async def trigger_task(
        self, account_id: str, req: TriggerEvalTaskRequest
    ) -> PositionEvalTask:
        """手动创建一个待执行任务"""
        config_name: Optional[str] = None
        symbols = req.symbols
        eval_dimensions = req.eval_dimensions
        extra_params = req.extra_params
        scope = req.scope.value

        # 若提供了 config_id，合并配置参数
        if req.config_id:
            config = await self.get_config(account_id, req.config_id)
            if config:
                config_name = config.name
                scope = config.scope
                symbols = symbols or config.symbols
                eval_dimensions = eval_dimensions or config.eval_dimensions
                extra_params = extra_params or config.extra_params

        task = PositionEvalTask(
            account_id=account_id,
            config_id=req.config_id,
            config_name=config_name,
            scope=scope,
            symbols=symbols,
            eval_dimensions=eval_dimensions,
            extra_params=extra_params,
            status="PENDING",
            triggered_by="manual",
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def batch_delete_pending(
        self, account_id: str, task_ids: List[int]
    ) -> int:
        """批量取消/删除待执行任务，返回实际影响行数"""
        result = await self.session.execute(
            select(PositionEvalTask).where(
                PositionEvalTask.id.in_(task_ids),
                PositionEvalTask.account_id == account_id,
                PositionEvalTask.status == "PENDING",
            )
        )
        tasks = result.scalars().all()
        for t in tasks:
            await self.session.delete(t)
        await self.session.commit()
        return len(tasks)

    # ─────────────────────────────────────────
    # 执行核心（异步后台执行）
    # ─────────────────────────────────────────

    async def run_task(self, account_id: str, task_id: int) -> PositionEvalTask:
        """立即同步执行指定任务（供路由中 background tasks 调用）"""
        task = await self.get_task(account_id, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status != "PENDING":
            raise ValueError(f"Task {task_id} is not in PENDING status (current: {task.status})")

        # 标记运行中
        task.status = "RUNNING"
        task.started_at = datetime.utcnow()
        await self.session.commit()

        try:
            results = await self._execute_evaluation(account_id, task)

            # 汇总统计
            evaluated = len(results)
            recommendation_counts: dict = {}
            for r in results:
                rec = r.get("recommendation", "UNKNOWN")
                recommendation_counts[rec] = recommendation_counts.get(rec, 0) + 1

            task.status = "DONE"
            task.completed_at = datetime.utcnow()
            task.evaluated_symbols = evaluated
            task.result_summary = {
                "total_evaluated": evaluated,
                "recommendation_counts": recommendation_counts,
                "avg_score": (
                    round(sum(r.get("overall_score", 0) for r in results) / evaluated, 1)
                    if evaluated else 0
                ),
            }
            task.result_detail = results
        except Exception as exc:
            logger.exception("PositionEvalTask %s failed: %s", task_id, exc)
            task.status = "FAILED"
            task.completed_at = datetime.utcnow()
            task.error_message = str(exc)

        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def _execute_evaluation(
        self, account_id: str, task: PositionEvalTask
    ) -> list:
        """内部：执行持仓评估，返回每个标的的结果列表"""
        from app.broker.factory import make_option_broker_client
        from app.services.position_scoring_service import PositionScoringService

        broker = make_option_broker_client()
        scorer = PositionScoringService()
        extra = task.extra_params or {}
        force_refresh = extra.get("force_refresh", False)

        # 确定目标标的列表
        if task.scope == "SYMBOL_LIST" and task.symbols:
            symbols = task.symbols
        else:
            # 从 broker 拉取当前持仓
            try:
                positions_raw = await broker.get_positions(account_id)
                symbols = [p.symbol for p in positions_raw if p.symbol]
            except Exception:
                symbols = []

        task.total_symbols = len(symbols)
        await self.session.commit()

        results = []
        for symbol in symbols:
            try:
                score_obj = await scorer.calculate_position_score(
                    symbol=symbol,
                    force_refresh=force_refresh,
                )
                if score_obj:
                    results.append({
                        "symbol": symbol,
                        "overall_score": getattr(score_obj, "overall_score", None),
                        "technical_score": getattr(score_obj, "technical_score", None),
                        "fundamental_score": getattr(score_obj, "fundamental_score", None),
                        "sentiment_score": getattr(score_obj, "sentiment_score", None),
                        "recommendation": getattr(score_obj, "recommendation", None),
                        "risk_level": getattr(score_obj, "risk_level", None),
                        "target_position": getattr(score_obj, "target_position", None),
                        "stop_loss": float(score_obj.stop_loss) if getattr(score_obj, "stop_loss", None) else None,
                        "take_profit": float(score_obj.take_profit) if getattr(score_obj, "take_profit", None) else None,
                        "status": "ok",
                    })
                else:
                    results.append({"symbol": symbol, "status": "skipped"})
            except Exception as exc:
                results.append({"symbol": symbol, "status": "error", "error": str(exc)})

        return results
