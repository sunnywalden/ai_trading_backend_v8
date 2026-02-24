"""统一任务配置 Schema"""
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime


class TaskType(str, Enum):
    OPPORTUNITY_SCAN = "OPPORTUNITY_SCAN"
    POSITION_EVAL = "POSITION_EVAL"
    DATA_WARMUP = "DATA_WARMUP"
    SYSTEM_HEALTH = "SYSTEM_HEALTH"


class TriggerMode(str, Enum):
    MANUAL = "MANUAL"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    CRON = "CRON"


class TaskTriggerConfigBase(BaseModel):
    task_type: TaskType
    name: str
    description: Optional[str] = None
    trigger_mode: TriggerMode = TriggerMode.MANUAL
    trigger_time: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    enabled: bool = True


class TaskTriggerConfigCreate(TaskTriggerConfigBase):
    pass


class TaskTriggerConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_mode: Optional[TriggerMode] = None
    trigger_time: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class TaskTriggerConfigView(TaskTriggerConfigBase):
    id: int
    account_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskTriggerConfigList(BaseModel):
    configs: List[TaskTriggerConfigView]
    total: int
