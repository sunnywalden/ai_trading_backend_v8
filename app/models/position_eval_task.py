"""持仓评估任务模型"""
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, JSON, Text, text, Index, ForeignKey
from app.models.db import Base


class PositionEvalTask(Base):
    """持仓评估任务

    生命周期：
      PENDING  -> RUNNING -> DONE
                           -> FAILED
      PENDING  -> CANCELLED（用户手动删除待执行任务）
    """
    __tablename__ = "position_eval_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, comment="账户ID")

    # 关联配置（可选，手动触发时可为空）
    config_id = Column(Integer, nullable=True, comment="关联配置ID")
    config_name = Column(String(128), nullable=True, comment="配置快照名称")

    # 任务描述
    scope = Column(String(16), nullable=False, default="ALL_POSITIONS")
    symbols = Column(JSON, nullable=True, comment="本次评估的标的列表快照")
    eval_dimensions = Column(JSON, nullable=False, comment="评估维度快照")
    extra_params = Column(JSON, nullable=True, comment="额外参数快照")

    # 状态
    status = Column(
        String(16), nullable=False, default="PENDING",
        comment="PENDING / RUNNING / DONE / FAILED / CANCELLED"
    )
    triggered_by = Column(String(32), nullable=False, default="manual", comment="manual / scheduler")

    # 执行时间
    scheduled_at = Column(DateTime, nullable=True, comment="计划执行时间")
    started_at = Column(DateTime, nullable=True, comment="实际开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    # 结果
    result_summary = Column(JSON, nullable=True, comment="执行结果摘要")
    result_detail = Column(JSON, nullable=True, comment="每个标的的详细评估结果列表")
    error_message = Column(Text, nullable=True, comment="失败原因")

    # 统计
    total_symbols = Column(Integer, nullable=True, comment="待评估标的数")
    evaluated_symbols = Column(Integer, nullable=True, comment="已完成评估标的数")

    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("idx_eval_task_account_status", "account_id", "status"),
        Index("idx_eval_task_config", "config_id"),
        Index("idx_eval_task_created", "created_at"),
    )
