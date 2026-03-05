"""V10.4.2: GhostTrade ORM 模型

被 Layer 3/4 拒绝的信号，系统自动创建"幽灵交易"进行无资金虚拟跟踪。
用于反事实验证：如果通过了漏斗，结果会是什么。
对比幽灵胜率 vs 实际胜率，作为动态校准漏斗参数的依据。

灵感来源：Bridgewater 的 Shadow Portfolio。
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class GhostTradeResult(str, enum.Enum):
    WIN     = "WIN"
    LOSS    = "LOSS"
    OPEN    = "OPEN"       # 仍在追踪期内
    EXPIRED = "EXPIRED"    # 超过最大追踪天数，未触及止盈/止损


class GhostTrade(Base):
    """ghost_trades — 幽灵交易虚拟跟踪表"""
    __tablename__ = "ghost_trades"

    id: Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 来源信号 ──
    signal_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True,
        comment="FK → trading_signals.id",
    )
    audit_log_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True,
        comment="FK → signal_quality_audit_logs.id",
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False,
        comment="LONG / SHORT",
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="冗余存储拒绝原因，方便查询",
    )
    rejected_at_layer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    conviction_score_at_rejection: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── 虚拟进场价格 ──
    entry_price:  Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── 追踪状态 ──
    max_tracking_days: Mapped[int]   = mapped_column(Integer, nullable=False, default=10)
    tracking_day:      Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    last_price:        Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    highest_price:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lowest_price:      Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── 虚拟损益 ──
    ghost_pnl_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="虚拟持仓收益率（每日更新）",
    )
    ghost_pnl_abs: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="虚拟绝对收益（基于 100 单位名义）",
    )
    ghost_result: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GhostTradeResult.OPEN,
        comment="WIN / LOSS / OPEN / EXPIRED",
    )

    # ── 价格历史（JSON 数组，方便绘图）──
    price_history: Mapped[Optional[list[dict]]] = mapped_column(
        JSON, nullable=True,
        comment="[{date, close, pnl_pct}, ...]，最多保留 max_tracking_days 条",
    )

    # ── 时间戳 ──
    tracking_start: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    tracking_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_gt_symbol_result",   "symbol", "ghost_result"),
        Index("idx_gt_tracking_start",  "tracking_start"),
        Index("idx_gt_direction",       "direction"),
    )
