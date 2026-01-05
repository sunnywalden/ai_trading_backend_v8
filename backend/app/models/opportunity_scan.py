"""机会扫描结果数据模型

用于“潜在机会模块”：
- 每日（北京时间 20:30）扫描固定股票池
- 结合技术/基本面/情绪评分 + 宏观风险，推荐 1-3 只标的

设计目标：
- 可追溯：记录每次扫描的参数、宏观风险快照、耗时与状态
- 可查询：支持获取 latest / 最近 N 次 / 单次详情
- 幂等：同一天同一 universe 只保留一条成功 run（通过 run_key 约束）
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.models.db import Base


class OpportunityScanRun(Base):
    __tablename__ = "opportunity_scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 幂等键（例如：2026-01-05|US_LARGE_MID_TECH|min75|max3）
    run_key = Column(String, nullable=False)

    # 扫描参数
    as_of = Column(DateTime, nullable=False)
    universe_name = Column(String, nullable=False, index=True)
    min_score = Column(Integer, nullable=False, default=75)
    max_results = Column(Integer, nullable=False, default=3)
    force_refresh = Column(Integer, nullable=False, default=0)  # 0/1

    # 宏观风险快照
    macro_overall_score = Column(Integer)
    macro_risk_level = Column(String)
    macro_risk_summary = Column(Text)

    # 执行元数据
    status = Column(String, nullable=False, default="SUCCESS")  # SUCCESS/FAILED/SKIPPED
    error_message = Column(Text)
    total_symbols = Column(Integer, default=0)
    qualified_symbols = Column(Integer, default=0)
    elapsed_ms = Column(Integer)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    items = relationship(
        "OpportunityScanItem",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("run_key", name="uq_opportunity_scan_runs_run_key"),
        Index("ix_opportunity_scan_runs_created_at", "created_at"),
    )


class OpportunityScanItem(Base):
    __tablename__ = "opportunity_scan_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("opportunity_scan_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    symbol = Column(String, nullable=False, index=True)

    # 三维评分 + 综合评分
    technical_score = Column(Integer)
    fundamental_score = Column(Integer)
    sentiment_score = Column(Integer)
    overall_score = Column(Integer)

    recommendation = Column(String)  # BUY / STRONG_BUY 等（与 PositionScoringService 一致）
    reason = Column(Text)  # 简要原因（JSON 或纯文本）

    current_price = Column(Float)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    run = relationship("OpportunityScanRun", back_populates="items")

    __table_args__ = (
        Index("ix_opportunity_scan_items_run_symbol", "run_id", "symbol"),
    )
