"""V10.2-M5: TradeAttributionEntry ORM 模型

存储每笔交易完成后的三层逐笔归因结果：
  Layer-1 Alpha 来源 / Layer-2 执行质量 / Layer-3 仓位管理
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class AttributionCategory(str, enum.Enum):
    WIN  = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class TradeAttributionEntry(Base):
    """trade_attribution_entries — 逐笔归因结果表"""
    __tablename__ = "trade_attribution_entries"

    id: Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 关联订单 ──
    position_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # ── 交易结果 ──
    entry_price:   Mapped[float] = mapped_column(Float, nullable=False)
    exit_price:    Mapped[float] = mapped_column(Float, nullable=False)
    quantity:      Mapped[float] = mapped_column(Float, nullable=False)
    pnl_absolute:  Mapped[float] = mapped_column(Float, nullable=False)
    pnl_pct:       Mapped[float] = mapped_column(Float, nullable=False)
    hold_days:     Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    category:      Mapped[str]   = mapped_column(String(16), nullable=False, default=AttributionCategory.WIN)

    # ── Layer-1: Alpha 来源归因 ──
    alpha_source: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="信号来源：TECHNICAL / FUNDAMENTAL / MACRO / VOLUME / OPTIONS / SENTIMENT",
    )
    alpha_contribution_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="该 alpha 来源贡献的收益百分比",
    )
    alpha_detail: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="6 维信号分解 JSON {'technical': 0.18, ...}",
    )

    # ── Layer-2: 执行质量归因 ──
    execution_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="执行质量评分 0-1",
    )
    slippage_pct:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timing_score:    Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="进入/退出时机评分")
    execution_detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── Layer-3: 仓位管理归因 ──
    position_mgmt_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scale_in_count:      Mapped[int]  = mapped_column(Integer, nullable=False, default=0)
    scale_out_reason:    Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trailing_stop_used:  Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position_detail:     Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── 系统上下文 ──
    regime_at_entry: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    regime_at_exit:  Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_attr_symbol",   "symbol"),
        Index("idx_attr_strategy", "strategy_id"),
        Index("idx_attr_created",  "created_at"),
        Index("idx_attr_category", "category"),
    )

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "symbol":         self.symbol,
            "pnl_pct":        self.pnl_pct,
            "pnl_absolute":   self.pnl_absolute,
            "hold_days":      self.hold_days,
            "category":       self.category,
            "alpha_source":   self.alpha_source,
            "alpha_contribution_pct": self.alpha_contribution_pct,
            "alpha_detail":   self.alpha_detail,
            "execution_score": self.execution_score,
            "slippage_pct":   self.slippage_pct,
            "timing_score":   self.timing_score,
            "position_mgmt_score": self.position_mgmt_score,
            "scale_in_count": self.scale_in_count,
            "scale_out_reason": self.scale_out_reason,
            "regime_at_entry": self.regime_at_entry,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
        }
