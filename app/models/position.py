"""V10.4.4: Position — 仓位聚合根（Position-centric 生命周期核心模型）

设计原则：
- Position 是整个交易生命周期的聚合根，所有 ExecutionSlice / PositionLifecycleEvent 都以 position_id 为外键关联。
- 唯一键策略：(account_id, symbol, thesis_key)，thesis_key 默认 "default"，支持同一账户同一标的开多个"主题仓位"。
- TradingSignal / TradingPlan / AutonomousExecutionIntent 降级为触发器 / 决策上下文 / 兼容层，不再主导生命周期。
- Position 状态由 position_lifecycle_manager 负责管理，不允许外部直接写 status 字段。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base

# ─────────────────────────────────────────────────────────────────────────────
# 枚举
# ─────────────────────────────────────────────────────────────────────────────


class PositionStatus(str, Enum):
    """Position 生命周期状态机（10 态）"""

    PENDING = "PENDING"  # 意图已创建，尚未有任何成交
    OPENING = "OPENING"  # 开仓 ExecutionSlice 进行中
    ACTIVE = "ACTIVE"  # 正常持仓（至少有一笔成交确认）
    SCALING_IN = "SCALING_IN"  # 加仓 ExecutionSlice 进行中
    SCALING_OUT = "SCALING_OUT"  # 减仓 ExecutionSlice 进行中
    CLOSING = "CLOSING"  # 平仓 ExecutionSlice 进行中
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"  # 部分平仓完成，仍有持仓
    EXCEPTION = "EXCEPTION"  # 需人工干预（stuck / partial fill 超时等）
    CLOSED = "CLOSED"  # 已全部平仓
    LIQUIDATED = "LIQUIDATED"  # 强制清算（circuit breaker / risk forced）


class ClosingReason(str, Enum):
    """平仓原因分类（审计用）"""

    VOLITIONAL = "VOLITIONAL"  # 主动策略平仓（信号驱动）
    STOP_LOSS = "STOP_LOSS"  # 触发止损线
    TAKE_PROFIT = "TAKE_PROFIT"  # 触发止盈线
    MAX_HOLDING_DAYS = "MAX_HOLDING_DAYS"  # 超过最大持仓天数
    RISK_FORCED = "RISK_FORCED"  # 风控强制平仓
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"  # 熔断触发
    PORTFOLIO_REBALANCE = "PORTFOLIO_REBALANCE"  # 组合再平衡
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"  # 人工强制干预
    REGIME_CHANGE = "REGIME_CHANGE"  # 市场体制切换触发
    THESIS_INVALIDATED = "THESIS_INVALIDATED"  # 逻辑失效（AI / 分析师判断）
    EXEMPTION_CLOSE = "EXEMPTION_CLOSE"  # 豁免后关闭


class ExecutionPath(str, Enum):
    """执行路径（治理追踪用）"""

    AUTONOMOUS = "AUTONOMOUS"  # AI 完全自主
    SEMI_AUTO = "SEMI_AUTO"  # 半自动（有撤单窗口）
    ADVISORY = "ADVISORY"  # 仅建议，人工审批后下单
    MANUAL = "MANUAL"  # 完全人工


# ─────────────────────────────────────────────────────────────────────────────
# Position 聚合根
# ─────────────────────────────────────────────────────────────────────────────


class Position(Base):
    """仓位聚合根 — V10.4.4

    生命周期入口：autonomous_engine 判断 ENTRY 动作时 upsert 一条 Position 记录。
    生命周期出口：position_lifecycle_manager 将状态推进到 CLOSED / LIQUIDATED。
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 坐标键 ────────────────────────────────────────────────────────────────
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    thesis_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="default",
        doc="用于区分同账户同标的多主题仓位，默认 'default'",
    )

    # ── 状态 ──────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PositionStatus.PENDING.value, index=True
    )

    # ── 方向 ──────────────────────────────────────────────────────────────────
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False, default="LONG", doc="LONG / SHORT"
    )

    # ── 数量 ──────────────────────────────────────────────────────────────────
    total_qty: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, doc="当前持有总数量（含所有成交后的净额）"
    )
    filled_qty: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, doc="累计成交数量（含加仓，不含减仓）"
    )
    open_qty: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="已开仓数量（= filled_qty - closed_qty）",
    )
    closed_qty: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, doc="累计已平仓数量"
    )

    # ── 成本 / 盈亏 ───────────────────────────────────────────────────────────
    avg_entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unrealized_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── 止损 / 止盈 ───────────────────────────────────────────────────────────
    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_high: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, doc="追踪止损用：历史最高价格"
    )
    max_holding_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── 信号 / 计划溯源（兼容层） ─────────────────────────────────────────────
    initial_signal_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, doc="触发开仓的第一个 TradingSignal.id"
    )
    initial_signal_uid: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="触发开仓的第一个 TradingSignal.signal_id（UUID）",
    )
    latest_plan_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, doc="最近关联的 TradingPlan.id"
    )

    # ── 关闭信息 ──────────────────────────────────────────────────────────────
    closing_reason: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, doc="ClosingReason 枚举值；CLOSED/LIQUIDATED 时必填"
    )
    closing_source: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, doc="ExecutionPath 枚举值"
    )
    closing_note: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, doc="人工备注 / AI 关闭摘要"
    )

    # ── 治理 / 豁免 ───────────────────────────────────────────────────────────
    exemption_active: Mapped[bool] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="True: 当前有活跃豁免（circuit breaker bypass）会影响 closing 判断",
    )
    exemption_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    governance_flag: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, doc="NORMAL / WATCHLIST / ESCALATED / SUSPENDED"
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────────
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, doc="第一笔成交时间（ACTIVE 状态确立时间）"
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_action_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, doc="最后一次 ExecutionSlice 动作时间"
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
    slices: Mapped[list["ExecutionSlice"]] = relationship(
        "ExecutionSlice", back_populates="position", lazy="select"
    )
    events: Mapped[list["PositionLifecycleEvent"]] = relationship(
        "PositionLifecycleEvent", back_populates="position", lazy="select"
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "symbol",
            "thesis_key",
            name="uq_position_account_symbol_thesis",
        ),
        Index("idx_position_account_status", "account_id", "status"),
        Index("idx_position_symbol_status", "symbol", "status"),
        Index("idx_position_closed_at", "closed_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Position id={self.id} {self.symbol} "
            f"status={self.status} qty={self.open_qty}>"
        )

    @property
    def is_open(self) -> bool:
        return self.status not in (
            PositionStatus.CLOSED.value,
            PositionStatus.LIQUIDATED.value,
        )

    @property
    def holding_days(self) -> int:
        if not self.opened_at:
            return 0
        delta = datetime.utcnow() - self.opened_at.replace(tzinfo=None)
        return delta.days


# ─────────────────────────────────────────────────────────────────────────────
# 延迟导入（避免循环依赖）
# ─────────────────────────────────────────────────────────────────────────────
from app.models.execution_slice import ExecutionSlice  # noqa: E402
from app.models.position_lifecycle_event import PositionLifecycleEvent  # noqa: E402
