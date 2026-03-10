from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class ExecutionPolicyProfile(Base):
    """执行策略反馈画像。

    按账户 / 标的 / 买卖方向 / 紧急度 / 算法类型聚合执行反馈，
    作为 ExecutionPolicyService 在冷启动或近期样本不足时的长期画像兜底。
    """

    __tablename__ = "execution_policy_profiles"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    urgency_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    algo_type: Mapped[str] = mapped_column(String(32), nullable=False)

    sample_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    avg_total_is_bps: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    avg_fill_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    avg_quality_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    last_total_is_bps: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    last_fill_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    last_quality_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )

    feedback_bias: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="NO_DATA",
    )
    recommended_algo: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    limit_offset_bps: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    participation_rate_multiplier: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
    )
    pressure_high: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    last_feedback_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index(
            "ux_exec_policy_profile_key",
            "account_id",
            "symbol",
            "side",
            "urgency_bucket",
            "algo_type",
            unique=True,
        ),
        Index(
            "idx_exec_policy_profile_lookup",
            "account_id",
            "symbol",
            "side",
            "urgency_bucket",
        ),
        {"comment": "执行策略长期反馈画像 V10.5.3"},
    )
