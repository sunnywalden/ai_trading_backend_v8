"""V10.2-M6: AIInsight + ABExperiment ORM 模型

ai_insight_repository — AI 系统从历史交易中提炼的经验规则库
ab_experiments       — 自动参数优化 A/B 实验记录
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class InsightType(str, enum.Enum):
    PATTERN       = "PATTERN"         # 识别到盈利模式
    TRAP          = "TRAP"            # 识别到亏损陷阱
    EXECUTION     = "EXECUTION"       # 执行改进建议
    PARAM_SUGGESTION = "PARAM_SUGGESTION"  # 参数调整建议


class ExperimentStatus(str, enum.Enum):
    RUNNING   = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"
    ABORTED   = "ABORTED"


class AIInsight(Base):
    """ai_insight_repository — AI 经验库"""
    __tablename__ = "ai_insight_repository"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 来源与分类 ──
    insight_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="InsightType 枚举",
    )
    regime: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
        comment="适用市场状态，NULL 表示全状态适用",
    )
    symbol: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
        comment="关联资产，NULL 表示全市场通用",
    )
    strategy_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # ── 洞察内容 ──
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Any] = mapped_column(
        JSON, nullable=True,
        comment="支撑证据：{'trade_ids': [...], 'win_rate': 0.72, 'sample_size': 34}",
    )
    actionable_rule: Mapped[Any] = mapped_column(
        JSON, nullable=True,
        comment="可执行规则：{'action': 'REDUCE_SIZE', 'condition': '...', 'params': {...}}",
    )

    # ── 可信度与效果 ──
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    win_rate_impact: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="应用该规则后胜率变化 delta",
    )
    validated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="是否通过 A/B 实验验证",
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="是否在决策流中激活该规则",
    )

    # ── 统计 ──
    applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="被应用次数")
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="应用后成功次数")

    created_by_job: Mapped[str] = mapped_column(String(64), nullable=False, default="weekly_insight_job")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_insight_type",   "insight_type"),
        Index("idx_insight_regime", "regime"),
        Index("idx_insight_active", "active"),
        Index("idx_insight_confidence", "confidence"),
    )

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "insight_type":  self.insight_type,
            "regime":        self.regime,
            "symbol":        self.symbol,
            "title":         self.title,
            "summary":       self.summary,
            "actionable_rule": self.actionable_rule,
            "confidence":    self.confidence,
            "win_rate_impact": self.win_rate_impact,
            "validated":     self.validated,
            "active":        self.active,
            "applied_count": self.applied_count,
            "success_count": self.success_count,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }


class ABExperiment(Base):
    """ab_experiments — 参数 A/B 实验记录"""
    __tablename__ = "ab_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 来源 insight ──
    insight_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    experiment_name: Mapped[str] = mapped_column(String(256), nullable=False)

    # ── 参数对比 ──
    param_key: Mapped[str] = mapped_column(
        String(128), nullable=False,
        comment="被测试的参数名称，如 'var_multiplier.HIGH_VOL'",
    )
    control_value: Mapped[Any] = mapped_column(JSON, nullable=True, comment="对照组参数")
    treatment_value: Mapped[Any] = mapped_column(JSON, nullable=True, comment="实验组参数")

    # ── 实验状态 ──
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ExperimentStatus.RUNNING)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date:   Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)

    # ── 结果 ──
    control_win_rate:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    treatment_win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    control_trades:     Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    treatment_trades:   Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    p_value:            Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    passed_significance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_applied:        Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_ab_status",   "status"),
        Index("idx_ab_start",    "start_date"),
    )

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "insight_id":       self.insight_id,
            "experiment_name":  self.experiment_name,
            "param_key":        self.param_key,
            "status":           self.status,
            "start_date":       self.start_date.isoformat() if self.start_date else None,
            "end_date":         self.end_date.isoformat() if self.end_date else None,
            "control_win_rate":   self.control_win_rate,
            "treatment_win_rate": self.treatment_win_rate,
            "p_value":          self.p_value,
            "passed_significance": self.passed_significance,
            "auto_applied":     self.auto_applied,
        }
