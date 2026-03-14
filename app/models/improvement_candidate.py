"""V11.0.1 — ImprovementCandidate ORM 模型

由 M3 改进引擎生成的改进候选条目，
记录每次系统自感知到的参数偏差和建议调整方向。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class ImprovementCandidate(Base):
    """改进候选条目表。"""

    __tablename__ = "improvement_candidates"

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

    # 改进目标描述
    candidate_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="parameter_tuning",
    )
    target_module: Mapped[str] = mapped_column(String(128), nullable=False)
    target_param: Mapped[str] = mapped_column(String(128), nullable=False)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 置信度与触发来源
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    trigger_source: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    # e.g. "friction_accumulation", "false_hold_repeat", "idle_capital_persist"

    # 状态
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )
    # pending / applied / rejected / expired

    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
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
            "ix_improvement_candidates_account_status",
            "account_id",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ImprovementCandidate id={self.id} "
            f"type={self.candidate_type} module={self.target_module} "
            f"param={self.target_param} "
            f"conf={self.confidence:.2f}>"
        )
