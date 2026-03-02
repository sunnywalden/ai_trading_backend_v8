"""portfolio_factor_exposure — V10.3.3 组合因子敞口快照表

每 5 分钟对持仓组合计算五因子（Market/HML/SMB/MOM/QMJ）Beta 敞口，
同时记录尾部风险指标 ES@97.5% 和持仓相关性矩阵摘要。
"""

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class PortfolioFactorExposure(Base):
    """五因子敞口 5 分钟快照 + ES@97.5%。"""

    __tablename__ = "portfolio_factor_exposure"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, comment="快照时间（UTC）")

    # Fama-French 五因子 + QMJ Beta
    beta_market: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="市场因子 Beta (MKT-RF)")
    beta_hml: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="价值因子 HML Beta")
    beta_smb: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="规模因子 SMB Beta")
    beta_mom: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="动量因子 MOM Beta")
    beta_qmj: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="质量因子 QMJ Beta")

    # 尾部风险
    var_99: Mapped[float | None] = mapped_column(Float, nullable=True, comment="VaR@99%（组合日收益%）")
    es_97_5: Mapped[float | None] = mapped_column(Float, nullable=True, comment="ES@97.5% 预期缺口（%）")
    volatility_annualized: Mapped[float | None] = mapped_column(Float, nullable=True, comment="年化波动率（%）")

    # 相关性摘要
    avg_pairwise_corr: Mapped[float | None] = mapped_column(Float, nullable=True, comment="持仓均值两两相关系数 -1~1")
    max_pairwise_corr: Mapped[float | None] = mapped_column(Float, nullable=True, comment="最大两两相关系数")
    correlation_spike: Mapped[bool] = mapped_column(default=False, comment="是否触发相关性骤升警报(>0.65)")
    top_corr_pair: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="最高相关对，如 AAPL-MSFT")

    # 组合元数据
    positions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="持仓数量")
    gross_exposure: Mapped[float | None] = mapped_column(Float, nullable=True, comment="总敞口 USD")
    net_exposure: Mapped[float | None] = mapped_column(Float, nullable=True, comment="净敞口 USD")
    portfolio_beta: Mapped[float | None] = mapped_column(Float, nullable=True, comment="组合整体 Beta")

    # 个股权重快照 JSON {symbol: weight}
    weights_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="持仓权重快照")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_pfe_user_snap", "user_id", "snapshot_at"),
        {"comment": "五因子敞口快照 V10.3.3"},
    )
