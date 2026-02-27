"""V10.2-M1: MarketRegime SQLAlchemy ORM 模型

存储每次体制分类的历史记录，便于前端展示时间轴及回测归因分析。
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.db import Base  # type: ignore[import]


class RegimeType(str, enum.Enum):
    """市场体制六分类"""
    BULL_TREND   = "BULL_TREND"   # 强势牛市趋势：动量领先，建议超配成长/趋势策略
    BEAR_TREND   = "BEAR_TREND"   # 熊市下行趋势：防御优先，减仓/止损
    HIGH_VOL     = "HIGH_VOL"     # 高波动率环境：期权溢价高，偏空头/对冲
    MEAN_REVERT  = "MEAN_REVERT"  # 均值回复环境：横盘震荡，均值回归策略占优
    RANGE_BOUND  = "RANGE_BOUND"  # 区间震荡，低波动窄幅：网格/高频策略
    CRISIS       = "CRISIS"       # 危机体制：极端恐慌，熔断保护，最小化仓位


class MarketRegime(Base):
    """
    市场体制历史表 market_regimes

    每条记录代表一次体制「确认切换」（3 天连续信号后写入）。
    raw_score_snapshot 存储五维原始得分 JSON 备查。
    """
    __tablename__ = "market_regimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 时间维度 ──
    classification_date: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="体制被确认的日期时间（UTC）",
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="体制生效开始时间",
    )
    valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        comment="体制生效结束时间（NULL 表示当前仍有效）",
    )

    # ── 体制结果 ──
    regime: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="RegimeType枚举值，如 BULL_TREND",
    )
    prev_regime: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        comment="前一个体制，首次为 NULL",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="分类置信度 [0,1]，基于五维评分集中度",
    )

    # ── 五维原始得分（各自 0~100）──
    trend_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="趋势强度得分")
    vol_score: Mapped[Optional[float]]   = mapped_column(Float, nullable=True, comment="波动率制度得分（高波动→高分）")
    breadth_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="市场广度得分（上涨家数比例）")
    macro_score: Mapped[Optional[float]]  = mapped_column(Float, nullable=True, comment="宏观环境评分（正→宽松，负→收紧）")
    momentum_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="价格动量得分")

    # ── 分类附注 ──
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="分类推理摘要（LLM 或规则说明）")

    # ── 人工干预标记 ──
    is_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True=管理员手动覆写，非自动分类",
    )
    override_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="覆写操作者账号",
    )

    # ── 元数据 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_market_regimes_date",  "classification_date"),
        Index("idx_market_regimes_regime", "regime"),
        Index("idx_market_regimes_valid",  "valid_from", "valid_until"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MarketRegime id={self.id} regime={self.regime} "
            f"confidence={self.confidence:.2f} date={self.classification_date.date()}>"
        )

    def to_dict(self) -> dict:
        """序列化为纯字典，供 API 响应用。"""
        return {
            "id": self.id,
            "regime": self.regime,
            "prev_regime": self.prev_regime,
            "confidence": round(self.confidence, 4),
            "classification_date": self.classification_date.isoformat() if self.classification_date else None,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "scores": {
                "trend":    self.trend_score,
                "vol":      self.vol_score,
                "breadth":  self.breadth_score,
                "macro":    self.macro_score,
                "momentum": self.momentum_score,
            },
            "reasoning": self.reasoning,
            "is_override": self.is_override,
            "override_by": self.override_by,
        }
