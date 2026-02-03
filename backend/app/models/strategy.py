from __future__ import annotations

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
from sqlalchemy.orm import relationship

from app.models.db import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False)
    style = Column(String(64))
    description = Column(Text)
    is_builtin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    owner_id = Column(String(64))
    version = Column(Integer, nullable=False, default=1)
    default_params = Column(JSON)
    signal_sources = Column(JSON)
    risk_profile = Column(JSON)
    tags = Column(JSON)
    last_run_status = Column(String(16))
    last_run_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    runs = relationship("StrategyRun", back_populates="strategy", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_strategy_name_version"),
        Index("ix_strategies_style", "style"),
        Index("ix_strategies_is_builtin", "is_builtin"),
    )


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    id = Column(String(36), primary_key=True)
    strategy_id = Column(String(36), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_version = Column(Integer, nullable=False)
    user_id = Column(String(64), nullable=False)
    account_id = Column(String(64), nullable=False)
    budget = Column(Numeric(20, 6))
    direction = Column(String(16))
    param_snapshot = Column(JSON)
    notify_channels = Column(JSON)
    target_universe = Column(String(64))
    status = Column(String(16), nullable=False, default="QUEUED")
    attempt = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    celery_task_id = Column(String(64), index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    strategy = relationship("Strategy", back_populates="runs")
    assets = relationship("StrategyRunAsset", back_populates="run", lazy="selectin")
    logs = relationship("StrategyRunLog", back_populates="run", lazy="selectin")
    notifications = relationship("StrategyNotification", back_populates="run", lazy="selectin")
    history = relationship("HistoricalStrategyRun", back_populates="run", uselist=False, lazy="selectin")

    __table_args__ = (
        Index("ix_strategy_runs_status", "status"),
    )


class HistoricalStrategyRun(Base):
    __tablename__ = "historical_strategy_runs"

    strategy_run_id = Column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), primary_key=True)
    run = relationship("StrategyRun", back_populates="history")
    hits = Column(Integer)
    scanned_total = Column(Integer)
    hit_rate = Column(Float)
    avg_signal_strength = Column(Float)
    assets = Column(JSON)
    timeline = Column(JSON)
    notify_channels = Column(JSON)
    status_payload = Column(JSON)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class StrategyRunAsset(Base):
    __tablename__ = "strategy_run_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_run_id = Column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    signal_strength = Column(Float)
    signal_dimensions = Column(JSON)
    weight = Column(Float)
    risk_flags = Column(JSON)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    run = relationship("StrategyRun", back_populates="assets")

    __table_args__ = (
        Index("ix_strategy_run_assets_run_symbol", "strategy_run_id", "symbol"),
    )


class StrategyRunLog(Base):
    __tablename__ = "strategy_run_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_run_id = Column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    phase = Column(String(32))
    message = Column(Text)
    details = Column(JSON)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    run = relationship("StrategyRun", back_populates="logs")

    __table_args__ = (
        Index("ix_strategy_run_logs_run_phase", "strategy_run_id", "phase"),
    )


class StrategyNotification(Base):
    __tablename__ = "strategy_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_run_id = Column(String(36), ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(32))
    status = Column(String(16))
    payload = Column(JSON)
    sent_at = Column(DateTime, server_default=func.now(), nullable=False)

    run = relationship("StrategyRun", back_populates="notifications")

    __table_args__ = (
        Index("ix_strategy_notifications_run_channel", "strategy_run_id", "channel"),
    )