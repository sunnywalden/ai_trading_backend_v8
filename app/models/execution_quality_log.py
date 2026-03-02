"""execution_quality_log — V10.3.3 执行质量日志表

记录每笔已完成 ExecutionIntent 的 IS (Implementation Shortfall) 四分解成本。
"""

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class ExecutionQualityLog(Base):
    """IS 四分解：delay_cost + market_impact_cost + opportunity_cost + timing_cost"""

    __tablename__ = "execution_quality_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    intent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="关联 autonomous_execution_intent.id")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # IS 四分解（bps 单位，正值=成本，负值=节省）
    delay_cost_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="决策→下单延迟成本 bps")
    market_impact_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="市场冲击成本 bps")
    opportunity_cost_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="机会成本 bps（未成交部分）")
    timing_cost_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="时机选择成本 bps")
    total_is_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="IS 总成本 bps")

    # 价格快照
    arrival_price: Mapped[float | None] = mapped_column(Float, nullable=True, comment="决策到达价（基准价）")
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True, comment="实际成交均价")
    mid_price_at_order: Mapped[float | None] = mapped_column(Float, nullable=True, comment="下单时中间价")
    vwap_reference: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当日 VWAP 参考价")

    # 执行元数据
    quantity_ordered: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_filled: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="成交率 0~1")
    time_to_fill_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="从下单到完成成交毫秒数")
    algo_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="TWAP/VWAP/LIMIT/MARKET")

    # 填充质量分 0~100
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合执行质量分 0~100")
    grade: Mapped[str | None] = mapped_column(String(4), nullable=True, comment="A/B/C/D/F")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_eql_user_symbol", "user_id", "symbol"),
        Index("idx_eql_created", "created_at"),
        {"comment": "IS 执行质量四分解日志 V10.3.3"},
    )
