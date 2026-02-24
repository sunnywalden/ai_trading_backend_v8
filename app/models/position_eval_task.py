"""持仓评估任务模型"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, JSON, Text, text, Index, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.db import Base


class PositionEvalTask(Base):
    """持仓评估任务

    生命周期：
      PENDING  -> RUNNING -> DONE
                           -> FAILED
      PENDING  -> CANCELLED（用户手动删除待执行任务）
    """
    __tablename__ = "position_eval_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="账户ID")

    # 关联配置（可选，手动触发时可为空）
    config_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="关联配置ID")
    config_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="配置快照名称")

    # 任务描述
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="ALL_POSITIONS")
    symbols: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, comment="本次评估的标的列表快照")
    eval_dimensions: Mapped[List[str]] = mapped_column(JSON, nullable=False, comment="评估维度快照")
    extra_params: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, comment="额外参数快照")

    # 状态
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING",
        comment="PENDING / RUNNING / DONE / FAILED / CANCELLED"
    )
    triggered_by: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", comment="manual / scheduler")

    # 执行时间
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="计划执行时间")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="实际开始时间")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="完成时间")

    # 结果
    result_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, comment="执行结果摘要")
    result_detail: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True, comment="每个标的的详细评估结果列表")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="失败原因")

    # 统计
    total_symbols: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="待评估标的数")
    evaluated_symbols: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="已完成评估标的数")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_eval_task_account_status", "account_id", "status"),
        Index("idx_eval_task_config", "config_id"),
        Index("idx_eval_task_created", "created_at"),
    )
