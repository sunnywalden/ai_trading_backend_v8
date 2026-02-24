from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    Float,
    Numeric,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.models.db import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    style: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_id: Mapped[Optional[str]] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    default_params: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    signal_sources: Mapped[Optional[List[str]]] = mapped_column(JSON)
    risk_profile: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON)
    last_run_status: Mapped[Optional[str]] = mapped_column(String(16))
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    runs: Mapped[List["StrategyRun"]] = relationship("StrategyRun", back_populates="strategy", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_strategy_name_version"),
        Index("ix_strategies_style", "style"),
        Index("ix_strategies_is_builtin", "is_builtin"),
    )


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[Optional[str]] = mapped_column(String(16))
    notify_channels: Mapped[Optional[List[str]]] = mapped_column(JSON)
    target_universe: Mapped[Optional[str]] = mapped_column(String(64))
    min_score: Mapped[Optional[int]] = mapped_column(Integer)
    max_results: Mapped[Optional[int]] = mapped_column(Integer)
    priority: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="runs", lazy="selectin")
    assets: Mapped[List["StrategyRunAsset"]] = relationship("StrategyRunAsset", back_populates="run", lazy="selectin")
    logs: Mapped[List["StrategyRunLog"]] = relationship("StrategyRunLog", back_populates="run", lazy="selectin")
    notifications: Mapped[List["StrategyNotification"]] = relationship("StrategyNotification", back_populates="run", lazy="selectin")
    history: Mapped[Optional["HistoricalStrategyRun"]] = relationship("HistoricalStrategyRun", back_populates="run", uselist=False, lazy="selectin")

    __table_args__ = (
        Index("ix_strategy_runs_status", "status"),
    )


class HistoricalStrategyRun(Base):
    __tablename__ = "historical_strategy_runs"

    strategy_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), primary_key=True)
    run: Mapped["StrategyRun"] = relationship("StrategyRun", back_populates="history")
    hits: Mapped[Optional[int]] = mapped_column(Integer)
    scanned_total: Mapped[Optional[int]] = mapped_column(Integer)
    hit_rate: Mapped[Optional[float]] = mapped_column(Float)
    avg_signal_strength: Mapped[Optional[float]] = mapped_column(Float)
    assets: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON)
    timeline: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON)
    notify_channels: Mapped[Optional[List[str]]] = mapped_column(JSON)
    status_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class StrategyRunAsset(Base):
    __tablename__ = "strategy_run_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_strength: Mapped[Optional[float]] = mapped_column(Float)
    signal_dimensions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    action: Mapped[Optional[str]] = mapped_column(String(16))  # BUY, SELL, HOLD, INCREASE
    direction: Mapped[Optional[str]] = mapped_column(String(16))  # LONG, SHORT
    risk_flags: Mapped[Optional[List[str]]] = mapped_column(JSON)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    run: Mapped["StrategyRun"] = relationship("StrategyRun", back_populates="assets")

    __table_args__ = (
        Index("ix_strategy_run_assets_run_symbol", "strategy_run_id", "symbol"),
    )


class StrategyRunLog(Base):
    __tablename__ = "strategy_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    phase: Mapped[Optional[str]] = mapped_column(String(32))
    message: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    run: Mapped["StrategyRun"] = relationship("StrategyRun", back_populates="logs")

    __table_args__ = (
        Index("ix_strategy_run_logs_run_phase", "strategy_run_id", "phase"),
    )


class StrategyNotification(Base):
    __tablename__ = "strategy_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[Optional[str]] = mapped_column(String(16))
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    run: Mapped["StrategyRun"] = relationship("StrategyRun", back_populates="notifications")

    __table_args__ = (
        Index("ix_strategy_notifications_run_channel", "strategy_run_id", "channel"),
    )