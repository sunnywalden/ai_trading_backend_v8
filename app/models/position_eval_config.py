"""持仓评估任务配置模型"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, text, Index
from app.models.db import Base


class PositionEvalConfig(Base):
    """持仓评估任务配置

    描述一个定期/手动触发的持仓评估规则：
    - 针对哪些标的（指定列表 or 当前全部持仓）
    - 使用哪种评估维度（technical / fundamental / composite）
    - 执行频率（manual / daily / weekly）
    """
    __tablename__ = "position_eval_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, comment="账户ID")

    name = Column(String(128), nullable=False, comment="配置名称")
    description = Column(Text, nullable=True, comment="备注说明")

    # 评估范围
    scope = Column(
        String(16), nullable=False, default="ALL_POSITIONS",
        comment="ALL_POSITIONS / SYMBOL_LIST"
    )
    symbols = Column(JSON, nullable=True, comment="指定symbol列表（scope=SYMBOL_LIST时使用）")

    # 评估维度
    eval_dimensions = Column(
        JSON, nullable=False,
        comment="评估维度列表: ['technical','fundamental','composite']"
    )

    # 触发方式
    trigger_mode = Column(
        String(16), nullable=False, default="MANUAL",
        comment="MANUAL / DAILY / WEEKLY"
    )
    trigger_time = Column(
        String(8), nullable=True,
        comment="定时触发时间（北京时间 UTC+8），格式 HH:MM，如 '09:30'（trigger_mode!=MANUAL时有效）"
    )

    # 状态
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")

    # 高级参数
    extra_params = Column(JSON, nullable=True, comment="额外参数，如 window_days、force_refresh 等")

    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index("idx_eval_cfg_account", "account_id"),
    )
