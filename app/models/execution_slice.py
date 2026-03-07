"""V10.4.4: ExecutionSlice — 执行切片（Position 的动作单元）

每一次针对仓位的操作（开仓 / 加仓 / 减仓 / 平仓）均对应一条 ExecutionSlice。
一条 ExecutionSlice 可关联一个或多个 broker 订单（通过 order_ids JSON 字段保存）。

状态流转：
  PENDING → SUBMITTED → PARTIALLY_FILLED → FILLED
                    ↘ FAILED / CANCELLED / STUCK
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class SliceAction(str, Enum):
    """执行切片动作类型"""

    OPEN = "OPEN"  # 开仓
    ADD = "ADD"  # 加仓
    REDUCE = "REDUCE"  # 减仓
    CLOSE = "CLOSE"  # 全部平仓
    PARTIAL = "PARTIAL"  # 部分平仓（显式）


class SliceStatus(str, Enum):
    """执行切片状态"""

    PENDING = "PENDING"  # 已创建，等待提交
    SUBMITTED = "SUBMITTED"  # 已向 broker 提交
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 部分成交
    FILLED = "FILLED"  # 全部成交
    FAILED = "FAILED"  # 执行失败
    CANCELLED = "CANCELLED"  # 已撤销
    STUCK = "STUCK"  # 超时未回报（需人工）
    SKIPPED = "SKIPPED"  # 被跳过（无可执行 qty）


class ExecutionSlice(Base):
    """执行切片 — V10.4.4

    position_lifecycle_manager 创建切片记录，order_executor 消费并更新切片状态。
    """

    __tablename__ = "execution_slices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 归属 ──────────────────────────────────────────────────────────────────
    position_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)

    # ── 动作 / 状态 ───────────────────────────────────────────────────────────
    action: Mapped[str] = mapped_column(
        String(16), nullable=False, doc="SliceAction 枚举值"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SliceStatus.PENDING.value, index=True
    )

    # ── 数量 ──────────────────────────────────────────────────────────────────
    requested_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    submitted_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    filled_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── 触发来源（兼容层溯源） ─────────────────────────────────────────────────
    signal_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, doc="触发本切片的 TradingSignal.signal_id（UUID）"
    )
    signal_db_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    intent_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="关联的 AutonomousExecutionIntent.intent_id（兼容旧链路）",
    )
    execution_path: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, doc="ExecutionPath 枚举值"
    )
    autonomy_level: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, doc="FULL / SEMI / ADVISORY"
    )

    # ── 关闭信息（仅 REDUCE / CLOSE 切片填写） ────────────────────────────────
    closing_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    exemption_applied: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    exemption_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── broker 订单 ───────────────────────────────────────────────────────────
    order_ids: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True, doc="broker 订单 ID 列表"
    )
    broker_ref: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, doc="主要 broker 订单 ID（快捷字段）"
    )

    # ── 错误 ──────────────────────────────────────────────────────────────────
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stuck_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, doc="切片进入 STUCK 状态的时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    # ── 关联 ──────────────────────────────────────────────────────────────────
    position: Mapped["Position"] = relationship("Position", back_populates="slices")

    __table_args__ = (
        Index("idx_slice_position_id", "position_id"),
        Index("idx_slice_account_status", "account_id", "status"),
        Index("idx_slice_stuck_at", "stuck_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionSlice id={self.id} pos={self.position_id} "
            f"action={self.action} status={self.status} qty={self.filled_qty}>"
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            SliceStatus.FILLED.value,
            SliceStatus.FAILED.value,
            SliceStatus.CANCELLED.value,
            SliceStatus.SKIPPED.value,
        )

    @property
    def fill_ratio(self) -> float:
        if not self.requested_qty:
            return 0.0
        return self.filled_qty / self.requested_qty


# 延迟导入，避免循环引用
from app.models.position import Position  # noqa: E402
