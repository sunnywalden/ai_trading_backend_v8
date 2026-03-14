"""V11.0.1 — MetaStateSnapshot ORM 模型

每个决策周期由 MetaStateSnapshotService 写入一条系统自知画像快照，
用于 M2.4 改进趋势对比与前端 Autonomy 页面展示。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class MetaStateSnapshot(Base):
    """系统元状态快照表。"""

    __tablename__ = "meta_state_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # 各维度摘要数量
    throttled_signals_count: Mapped[int] = mapped_column(Integer, default=0)
    false_hold_count: Mapped[int] = mapped_column(Integer, default=0)
    total_blocked_signals: Mapped[int] = mapped_column(Integer, default=0)

    # 资本状态
    idle_cash_ratio: Mapped[float | None] = mapped_column(nullable=True)
    gross_exposure_pct: Mapped[float | None] = mapped_column(nullable=True)

    # 完整 JSON 数据（前端详细展示用）
    snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index(
            "ix_meta_state_snapshots_account_generated", "account_id", "generated_at"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MetaStateSnapshot id={self.id} "
            f"account={self.account_id} blocked={self.total_blocked_signals}>"
        )
