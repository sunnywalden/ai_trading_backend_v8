"""V10.4.4: PositionLifecycleEvent — 仓位生命周期事件时间线（不可变审计流）

设计原则：
- 只追加（append-only），禁止更新或删除——作为合规审计源。
- 每一次状态迁移 / 风控决定 / 人工干预 / 豁免 / 异常 均写入一条记录。
- 前端 Position Detail 的 Timeline 直接展示本表排序后的全部事件。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class EventKind(str, Enum):
    """事件类型枚举"""

    # ── 状态迁移 ─────────────────────────────────────────────
    STATE_TRANSITION = "STATE_TRANSITION"  # PositionStatus 迁移
    # ── 执行切片 ─────────────────────────────────────────────
    SLICE_CREATED = "SLICE_CREATED"
    SLICE_SUBMITTED = "SLICE_SUBMITTED"
    SLICE_FILLED = "SLICE_FILLED"
    SLICE_PARTIALLY_FILLED = "SLICE_PARTIALLY_FILLED"
    SLICE_STUCK = "SLICE_STUCK"
    SLICE_FAILED = "SLICE_FAILED"
    SLICE_CANCELLED = "SLICE_CANCELLED"
    # ── 风控 / 治理 ──────────────────────────────────────────
    RISK_GATE_PASS = "RISK_GATE_PASS"
    RISK_GATE_BLOCK = "RISK_GATE_BLOCK"
    EXEMPTION_GRANTED = "EXEMPTION_GRANTED"
    EXEMPTION_REVOKED = "EXEMPTION_REVOKED"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    # ── 人工干预 ─────────────────────────────────────────────
    MANUAL_CLOSE = "MANUAL_CLOSE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    GOVERNANCE_REVIEW = "GOVERNANCE_REVIEW"
    # ── 价格更新 ─────────────────────────────────────────────
    PNL_SNAPSHOT = "PNL_SNAPSHOT"
    STOP_ADJUSTED = "STOP_ADJUSTED"
    # ── 系统 ─────────────────────────────────────────────────
    EXCEPTION_RAISED = "EXCEPTION_RAISED"
    EXCEPTION_CLEARED = "EXCEPTION_CLEARED"
    BROKER_SYNC = "BROKER_SYNC"  # broker 主动同步更新
    REGIME_CHANGE = "REGIME_CHANGE"


class PositionLifecycleEvent(Base):
    """仓位生命周期事件 — V10.4.4（Append-Only 审计时间线）"""

    __tablename__ = "position_lifecycle_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 归属 ──────────────────────────────────────────────────────────────────
    position_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slice_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("execution_slices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── 事件 ──────────────────────────────────────────────────────────────────
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, doc="EventKind 枚举值"
    )
    summary: Mapped[str] = mapped_column(
        String(256), nullable=False, doc="人类可读摘要（前端 timeline 展示）"
    )
    detail: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, doc="详细描述 / AI 推理 / 错误消息"
    )

    # ── 状态迁移（STATE_TRANSITION 类型时填写） ───────────────────────────────
    from_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # ── 关联实体 ──────────────────────────────────────────────────────────────
    actor: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="事件触发者：'system' / 'ai' / 'risk_gate' / 用户名",
    )
    signal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    intent_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ── 上下文快照（结构化，供 API 序列化） ──────────────────────────────────
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        doc="附加上下文快照：price、qty、pnl、regime、exemption_detail 等",
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
        doc="事件发生时间（UTC），时间线排序依据",
    )

    # ── 关联 ──────────────────────────────────────────────────────────────────
    position: Mapped["Position"] = relationship("Position", back_populates="events")

    __table_args__ = (
        Index("idx_ple_position_occurred", "position_id", "occurred_at"),
        Index("idx_ple_kind_occurred", "kind", "occurred_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<PositionLifecycleEvent id={self.id} "
            f"pos={self.position_id} kind={self.kind}>"
        )


# 延迟导入
from app.models.position import Position  # noqa: E402
