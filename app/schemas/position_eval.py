"""持仓评估任务相关 Pydantic Schemas"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


# ─────────────────────────────────────────
# Enums（与模型保持一致）
# ─────────────────────────────────────────

class EvalScope(str, Enum):
    ALL_POSITIONS = "ALL_POSITIONS"
    SYMBOL_LIST = "SYMBOL_LIST"


class EvalTriggerMode(str, Enum):
    MANUAL = "MANUAL"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


class EvalTaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ─────────────────────────────────────────
# Config Schemas
# ─────────────────────────────────────────

class PositionEvalConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="配置名称")
    description: Optional[str] = Field(None, max_length=500)
    scope: EvalScope = EvalScope.ALL_POSITIONS
    symbols: Optional[List[str]] = Field(None, description="scope=SYMBOL_LIST 时必填")
    eval_dimensions: List[str] = Field(
        default=["composite"],
        description="评估维度列表: technical / fundamental / composite"
    )
    trigger_mode: EvalTriggerMode = EvalTriggerMode.MANUAL
    trigger_time: Optional[str] = Field(None, description="定时触发时间 HH:MM")
    enabled: bool = True
    extra_params: Optional[Dict[str, Any]] = None


class PositionEvalConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    scope: Optional[EvalScope] = None
    symbols: Optional[List[str]] = None
    eval_dimensions: Optional[List[str]] = None
    trigger_mode: Optional[EvalTriggerMode] = None
    trigger_time: Optional[str] = None
    enabled: Optional[bool] = None
    extra_params: Optional[Dict[str, Any]] = None


class PositionEvalConfigView(BaseModel):
    id: int
    account_id: str
    name: str
    description: Optional[str]
    scope: str
    symbols: Optional[List[str]]
    eval_dimensions: List[str]
    trigger_mode: str
    trigger_time: Optional[str]
    enabled: bool
    extra_params: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# Task Schemas
# ─────────────────────────────────────────

class TriggerEvalTaskRequest(BaseModel):
    """手动触发持仓评估任务"""
    config_id: Optional[int] = Field(None, description="使用指定配置触发，为空则使用下方参数")
    scope: EvalScope = EvalScope.ALL_POSITIONS
    symbols: Optional[List[str]] = Field(None, description="scope=SYMBOL_LIST 时指定")
    eval_dimensions: List[str] = Field(default=["composite"])
    extra_params: Optional[Dict[str, Any]] = None


class BatchDeleteTasksRequest(BaseModel):
    task_ids: List[int] = Field(..., min_length=1, description="待删除的任务ID列表")


class PositionEvalTaskView(BaseModel):
    id: int
    account_id: str
    config_id: Optional[int]
    config_name: Optional[str]
    scope: str
    symbols: Optional[List[str]]
    eval_dimensions: List[str]
    extra_params: Optional[Dict[str, Any]]
    status: str
    triggered_by: str
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result_summary: Optional[Dict[str, Any]]
    error_message: Optional[str]
    total_symbols: Optional[int]
    evaluated_symbols: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class PositionEvalTaskDetailView(PositionEvalTaskView):
    """包含逐标的详细结果"""
    result_detail: Optional[List[Dict[str, Any]]]


class PositionEvalConfigListResponse(BaseModel):
    total: int
    items: List[PositionEvalConfigView]


class PositionEvalTaskListResponse(BaseModel):
    total: int
    items: List[PositionEvalTaskView]
