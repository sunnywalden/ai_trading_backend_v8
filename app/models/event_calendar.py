"""V10.2-M2: EventCalendarEntry SQLAlchemy ORM 模型

存储每个被记录的市场事件（财报/宏观日历/指数调整/分红）。
支持前端日历视图及后端风险围栏决策。
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class EventType(str, enum.Enum):
    EARNINGS          = "EARNINGS"           # 财报发布
    DIVIDEND          = "DIVIDEND"           # 股息/除权
    FOMC              = "FOMC"               # 美联储议息
    MACRO_DATA        = "MACRO_DATA"         # 非农/CPI/PCE 等宏观数据
    INDEX_REBALANCE   = "INDEX_REBALANCE"    # 指数成分调整
    SPLIT             = "SPLIT"              # 股票拆分/合并
    OTHER             = "OTHER"              # 其他重大事件


class EventRiskLevel(str, enum.Enum):
    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"
    EXTREME = "EXTREME"


class EventCalendarEntry(Base):
    """市场事件日历表 event_calendar_entries

    每条记录对应一个资产的具体事件，支持重复唯一索引（symbol + event_date + event_type）。
    """
    __tablename__ = "event_calendar_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 事件基本信息 ──
    symbol: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="关联股票代码，宏观事件为空字符串或 'MARKET'",
    )
    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="EventType 枚举值",
    )
    event_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        comment="事件预计发生日期（UTC）",
    )
    title: Mapped[str] = mapped_column(
        String(256), nullable=False,
        comment="事件标题，如 'AAPL Q4 2025 Earnings'",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="事件详情、预期值等",
    )

    # ── 财报专属字段 ──
    eps_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="预期 EPS")
    eps_actual:   Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="实际 EPS（财报后填入）")
    revenue_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    revenue_actual:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── 风险属性 ──
    risk_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EventRiskLevel.MEDIUM,
        comment="EventRiskLevel 枚举",
    )
    requires_fence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="是否需要触发风险围栏（减仓保护）",
    )
    fence_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="围栏动作是否已执行",
    )
    fence_applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # ── 围栏被覆盖（人工干预）──
    fence_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fence_override_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # ── 元数据 ──
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, default="yfinance",
        comment="数据来源：yfinance / tiger / fred / manual",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_event_symbol_date",   "symbol", "event_date"),
        Index("idx_event_type_date",     "event_type", "event_date"),
        Index("idx_event_fence_pending", "fence_applied", "event_date"),
        # V10.3: 唯一索引，防止多来源或重复抓取导致入库重复行
        Index("idx_event_unique_key", "symbol", "event_type", "event_date", "title", unique=True),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EventCalendarEntry {self.symbol} {self.event_type} {self.event_date.date()}>"

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "symbol":       self.symbol,
            "event_type":   self.event_type,
            "event_date":   self.event_date.isoformat() if self.event_date else None,
            "title":        self.title,
            "description":  self.description,
            "eps_estimate": self.eps_estimate,
            "eps_actual":   self.eps_actual,
            "risk_level":   self.risk_level,
            "requires_fence":   self.requires_fence,
            "fence_applied":    self.fence_applied,
            "fence_overridden": self.fence_overridden,
            "source":       self.source,
        }
