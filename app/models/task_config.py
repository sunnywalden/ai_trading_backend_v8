"""统一任务配置模型"""
from typing import Optional, Any, Dict
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class TaskTriggerConfig(Base):
    """统一任务触发配置

    用于管理系统中各类自动化任务的触发规则：
    - 机会扫描 (OPPORTUNITY_SCAN)
    - 持仓评估 (POSITION_EVAL)
    - 数据预热 (DATA_WARMUP) 等
    """
    __tablename__ = "task_trigger_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="账户ID")
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="任务类型")
    
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="配置名称")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="任务描述")

    # 触发方式
    trigger_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="MANUAL",
        comment="MANUAL / DAILY / WEEKLY / CRON"
    )
    trigger_time: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="触发时间设定（HH:MM 或 Cron 表达式）"
    )

    # 任务特定参数
    params: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, comment="任务执行所需的参数")

    # 状态
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index("idx_task_cfg_account_type", "account_id", "task_type"),
    )
