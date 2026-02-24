"""统一任务配置服务的业务实现层"""
import logging
from datetime import datetime
from typing import List, Optional, Any
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_config import TaskTriggerConfig
from app.schemas.task_config import TaskTriggerConfigCreate, TaskTriggerConfigUpdate, TaskType

logger = logging.getLogger(__name__)


class TaskTriggerConfigService:
    """系统统一任务配置服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_configs(
        self, account_id: str, task_type: Optional[TaskType] = None
    ) -> List[TaskTriggerConfig]:
        """获取任务配置列表"""
        # 确保默认配置存在
        await self.ensure_default_configs(account_id)

        stmt = select(TaskTriggerConfig).where(TaskTriggerConfig.account_id == account_id)
        if task_type:
            stmt = stmt.where(TaskTriggerConfig.task_type == task_type.value)
        
        stmt = stmt.order_by(TaskTriggerConfig.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def ensure_default_configs(self, account_id: str):
        """确保每种类型的任务都有至少一个默认配置"""
        default_names = {
            TaskType.OPPORTUNITY_SCAN: "机会扫描默认配置",
            TaskType.POSITION_EVAL: "持仓评估默认配置",
            TaskType.DATA_WARMUP: "数据预热默认配置",
            TaskType.SYSTEM_HEALTH: "系统健康自检配置",
        }
        
        for t_type, name in default_names.items():
            # 检查是否已存在该类型的配置
            stmt = select(func.count(TaskTriggerConfig.id)).where(
                and_(
                    TaskTriggerConfig.account_id == account_id,
                    TaskTriggerConfig.task_type == t_type.value
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            
            if count == 0:
                # 创建默认配置
                config = TaskTriggerConfig(
                    account_id=account_id,
                    task_type=t_type.value,
                    name=name,
                    description=f"系统预设的{name}，触发时刻为盘前最后30分钟",
                    trigger_mode="DAILY",
                    trigger_time="09:00",  # 盘前交易时段最后的30分钟 (09:00 - 09:30)
                    params={},
                    enabled=True,
                )
                self.session.add(config)
        
        await self.session.commit()

    async def get_config(self, account_id: str, config_id: int) -> Optional[TaskTriggerConfig]:
        """获取单个任务配置详情"""
        result = await self.session.execute(
            select(TaskTriggerConfig).where(
                TaskTriggerConfig.id == config_id,
                TaskTriggerConfig.account_id == account_id
            )
        )
        return result.scalar_one_or_none()

    async def create_config(
        self, account_id: str, data: TaskTriggerConfigCreate
    ) -> TaskTriggerConfig:
        """创建新任务配置"""
        config = TaskTriggerConfig(
            account_id=account_id,
            task_type=data.task_type.value,
            name=data.name,
            description=data.description,
            trigger_mode=data.trigger_mode.value,
            trigger_time=data.trigger_time,
            params=data.params,
            enabled=data.enabled,
        )
        self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def update_config(
        self, account_id: str, config_id: int, data: TaskTriggerConfigUpdate
    ) -> Optional[TaskTriggerConfig]:
        """更新任务配置"""
        config = await self.get_config(account_id, config_id)
        if config is None:
            return None
            
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(value, "value"):
                value = value.value
            setattr(config, field, value)
            
        config.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def delete_config(self, account_id: str, config_id: int) -> bool:
        """删除任务配置"""
        config = await self.get_config(account_id, config_id)
        if config is None:
            return False
        await self.session.delete(config)
        await self.session.commit()
        return True

    async def toggle_enabled(self, account_id: str, config_id: int, enabled: bool) -> Optional[TaskTriggerConfig]:
        """快速启停任务配置"""
        config = await self.get_config(account_id, config_id)
        if config is None:
            return None
        config.enabled = enabled
        config.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(config)
        return config
