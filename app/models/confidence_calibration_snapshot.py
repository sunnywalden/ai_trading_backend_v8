"""confidence_calibration_snapshot — V10.3.3 置信度校准快照表

每日 08:15 运行一次，统计过去 90 天每个置信度 bucket 和实际胜率之间的映射，
同时计算 Brier Score 和 ECE（Expected Calibration Error）。
"""

from datetime import date, datetime
from sqlalchemy import BigInteger, Date, DateTime, Float, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class ConfidenceCalibrationSnapshot(Base):
    """日度置信度校准快照——Brier Score + ECE + bucket 映射。"""

    __tablename__ = "confidence_calibration_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="快照日期（每日 08:15 生成）")

    # 全局校准指标
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Brier Score（越小越好，0~1）")
    ece: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Expected Calibration Error（越小越好）")
    overconfidence_bias: Mapped[float | None] = mapped_column(Float, nullable=True, comment="过度自信偏差（正值=高估置信）")

    # Bucket 映射 JSON 数组：[{bucket: "0.5-0.6", count: 23, predicted_rate: 0.55, actual_rate: 0.48, gap: 0.07}]
    calibration_buckets: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 样本元数据
    lookback_days: Mapped[int] = mapped_column(BigInteger, nullable=False, default=90, comment="回看窗口天数")
    total_samples: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    valid_bucket_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="样本充足的 bucket 数量")

    # 校准调整
    needs_adjustment: Mapped[bool] = mapped_column(default=False, comment="ECE > 0.12 需要降评调整")
    adjustment_factor: Mapped[float | None] = mapped_column(Float, nullable=True, comment="收缩因子 0~1，向 0.5 收缩")
    adjustment_applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_ccs_user_date", "user_id", "snapshot_date", unique=True),
        {"comment": "置信度校准快照 V10.3.3"},
    )
