"""V10.5.2: CapacityDecisionLog — 席位竞争决策审计日志

每当 CapacityArbiterService 触发一次席位竞争仲裁，均记录一条日志：
包含候选池快照、淘汰方案、审批通过信号，以及保护机制触发原因。
用于 QuantLoop Dashboard 的席位竞争时间线展示与参数校准。
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class ArbiterTriggerReason(str, enum.Enum):
    CAPACITY_OVERFLOW = "CAPACITY_OVERFLOW"  # 持仓数 + 信号数 > 上限
    PREEMPTIVE_EVALUATION = "PREEMPTIVE_EVALUATION"  # 预防性评估（持仓数 >= 上限 - 1）


class CapacityDecisionLog(Base):
    """capacity_decision_logs — 席位竞争仲裁审计日志表 (V10.5.2)"""

    __tablename__ = "capacity_decision_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 上下文 ──
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cycle_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="决策周期唯一 ID，同一 run_decision_cycle 内共享",
    )
    regime: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    trigger_reason: Mapped[str] = mapped_column(
        String(64), nullable=False, default=ArbiterTriggerReason.CAPACITY_OVERFLOW
    )

    # ── 容量快照 ──
    max_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    positions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    signals_count: Mapped[int] = mapped_column(Integer, nullable=False)
    overflow_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="N = positions_count + signals_count - max_positions",
    )

    # ── 候选池快照（JSON 数组）──
    candidates_snapshot: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="[{symbol, type:POSITION|SIGNAL, raw_score, admission_score, protected, rank}]",
    )

    # ── 仲裁结果 ──
    eliminated_positions: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="[{symbol, overall_score, hold_minutes, exit_signal_id}]",
    )
    eliminated_signals: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="[{signal_id, symbol, conviction_score, rejection_reason}]",
    )
    approved_signals: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="[{signal_id, symbol, conviction_score, admission_score}]",
    )

    # ── 保护机制 ──
    min_edge_protected: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="因 MIN_REPLACEMENT_EDGE 不足而跳过替换的候选数",
    )
    cooldown_protected: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="因替换冷却期而受保护的持仓数"
    )
    min_hold_protected: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="因最小持有时间而受保护的持仓数"
    )
    max_replacements_cap: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="因 MAX_REPLACEMENTS_PER_CYCLE 上限而中止的替换数",
    )

    # ── 标志 ──
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="仅评估，不触发实际平仓或拒绝"
    )
    replacement_triggered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否至少有 1 个持仓被替换"
    )

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (Index("ix_cdl_account_created", "account_id", "created_at"),)
