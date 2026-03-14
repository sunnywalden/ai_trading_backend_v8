"""V10.4.2: SignalQualityAuditLog ORM 模型

每个经过五层漏斗的信号（无论通过还是被拒）都会记录一条审计条目。
用于 Signal Watchtower 页面的拒绝分布分析和参数校准依据。
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class FunnelResult(str, enum.Enum):
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class RejectionReason(str, enum.Enum):
    LOW_LIQUIDITY = "LOW_LIQUIDITY"  # Layer 0
    REGIME_BLOCKED = "REGIME_BLOCKED"  # Layer 1: CRISIS/BEAR 方向限制
    REGIME_DIRECTION = "REGIME_DIRECTION"  # Layer 1: 体制要求 SHORT，信号为 LONG
    MAX_POSITIONS_REACHED = (
        "MAX_POSITIONS_REACHED"  # Layer 2: 持仓数达上限（硬拒绝，已弃用）
    )
    DAILY_QUOTA_EXHAUSTED = "DAILY_QUOTA_EXHAUSTED"  # Layer 2: 日配额耗尽
    HIGH_CORRELATION = "HIGH_CORRELATION"  # Layer 2: 与现有持仓相关性过高
    MISSING_RESONANCE_METADATA = (
        "MISSING_RESONANCE_METADATA"  # Layer 3: 信号缺少共振元数据，无法进行有效评估
    )
    INSUFFICIENT_RESONANCE = "INSUFFICIENT_RESONANCE"  # Layer 3: 同向维度不足
    ANTI_RESONANCE_KILL = "ANTI_RESONANCE_KILL"  # Layer 3: 一票否决
    LOW_CONVICTION = "LOW_CONVICTION"  # Layer 4: Conviction Score 不足
    LOW_EXPECTED_SHARPE = "LOW_EXPECTED_SHARPE"  # Layer 4: 预期夏普不足
    LOW_CALIBRATED_FLOOR = "LOW_CALIBRATED_FLOOR"  # Layer 4: 校准下界不足
    # V10.5.2 ── 席位竞争准入
    SEAT_COMPETITION_ELIMINATED = (
        "SEAT_COMPETITION_ELIMINATED"  # V10.5.2: 信号在席位竞争中被淘汰
    )


class SignalQualityAuditLog(Base):
    """signal_quality_audit_logs — 信号漏斗审计日志表"""

    __tablename__ = "signal_quality_audit_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ── 关联原始信号 ──
    signal_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="FK → trading_signals.id（可能为 None，若信号来自外部评估）",
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # ── 漏斗结果 ──
    funnel_result: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=FunnelResult.REJECTED,
        comment="PASSED / REJECTED",
    )
    rejected_at_layer: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="拒绝发生在第几层（0~4），PASSED 时为 null",
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="拒绝原因枚举值",
    )
    rejection_detail: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="人可读的详细拒绝说明",
    )

    # ── 评分详情 ──
    conviction_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    composite_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    resonance_bonus: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    regime_alignment: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    calibrated_lower_bound: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # ── 共振详情 ──
    aligned_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    aligned_dims: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="同向维度名列表 ['technical', 'options', ...]",
    )
    opposing_dims: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="反向维度名列表",
    )
    neutral_dims: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="中性维度名列表",
    )
    anti_resonance_triggered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # ── 上下文快照 ──
    signal_direction: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )  # LONG / SHORT
    regime: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    concurrent_positions: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    daily_signals_used: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    # ── 时间戳 ──
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index("idx_sqal_symbol_created", "symbol", "created_at"),
        Index("idx_sqal_funnel_result", "funnel_result"),
        Index("idx_sqal_signal_id", "signal_id"),
    )
