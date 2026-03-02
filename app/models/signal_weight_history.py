"""signal_weight_history — V10.3.3 信号权重演化历史表

由 AdaptiveFactorWeightingService 写入：
- Kalman Filter 在线权重更新（Q=0.001, R=0.01）
- 因子动量调整（TOP-2 IC 排名 +5%，末位 -5%）
- 每日收盘后运行
"""

from datetime import date, datetime
from sqlalchemy import BigInteger, Date, DateTime, Float, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class SignalWeightHistory(Base):
    """信号/因子权重演化快照——Kalman Filter 每日更新记录。"""

    __tablename__ = "signal_weight_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    record_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="权重计算日期")

    # 因子维度（与 signal_fusion_engine._DIM_WEIGHTS 对应）
    dimension: Mapped[str] = mapped_column(String(64), nullable=False, comment="如 technical/fundamental/ml/sentiment/macro/event")

    # 权重数据
    weight_before: Mapped[float] = mapped_column(Float, nullable=False, comment="Kalman 更新前权重")
    weight_after: Mapped[float] = mapped_column(Float, nullable=False, comment="Kalman 更新后权重")
    weight_momentum_adjusted: Mapped[float | None] = mapped_column(Float, nullable=True, comment="动量调整后最终权重（归一化）")

    # Kalman 状态
    kalman_gain: Mapped[float | None] = mapped_column(Float, nullable=True, comment="本次 Kalman 增益 K")
    process_noise: Mapped[float] = mapped_column(Float, nullable=False, default=0.001, comment="Q（过程噪声）")
    measurement_noise: Mapped[float] = mapped_column(Float, nullable=False, default=0.01, comment="R（观测噪声）")
    posterior_variance: Mapped[float | None] = mapped_column(Float, nullable=True, comment="后验方差 P")

    # IC 观测
    ic_5d: Mapped[float | None] = mapped_column(Float, nullable=True, comment="5 日 IC（Kalman 观测值）")
    ic_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_60d: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_rank: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="本日 IC 排名（1=最高）")

    # 动量调整原因
    momentum_adjustment: Mapped[float | None] = mapped_column(Float, nullable=True, comment="+0.05 / -0.05 / 0")
    adjustment_reason: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="TOP2_BONUS / BOTTOM_PENALTY / NO_ADJUST")

    # 全局权重快照（本日所有维度最终权重 JSON）
    global_weights_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_swh_user_date_dim", "user_id", "record_date", "dimension", unique=True),
        Index("idx_swh_date", "record_date"),
        {"comment": "Kalman 信号权重演化历史 V10.3.3"},
    )
