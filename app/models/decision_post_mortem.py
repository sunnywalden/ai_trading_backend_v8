"""decision_post_mortem — V10.3.3 决策事后剖析表

每笔仓位平仓后由 DecisionPostMortemService 调用 deepseek-reasoner
生成反事实三路径分析，并写入本表，同时自动生成 source=POST_MORTEM 的 Insight。
"""

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Float, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class DecisionPostMortem(Base):
    """平仓后 AI 反事实剖析报告。"""

    __tablename__ = "decision_post_mortems"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trade_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="关联 trading_plan.id 或 journal.id")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 交易结果上下文
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    hold_days: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="BUY/SELL")

    # AI 反事实分析内容
    factual_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="事实摘要：实际交易路径描述")
    counterfactual_buy: Mapped[str | None] = mapped_column(Text, nullable=True, comment="反事实路径 A：如果当时买入...")
    counterfactual_hold: Mapped[str | None] = mapped_column(Text, nullable=True, comment="反事实路径 B：如果当时持有...")
    counterfactual_sell: Mapped[str | None] = mapped_column(Text, nullable=True, comment="反事实路径 C：如果当时卖出...")
    key_lessons: Mapped[str | None] = mapped_column(Text, nullable=True, comment="关键教训（结构化要点）")
    improvement_suggestions: Mapped[str | None] = mapped_column(Text, nullable=True, comment="改进建议")

    # 模式标签（AI 自动提取）
    pattern_tags: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="如 ['chasing_momentum', 'premature_exit']")
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="主要错误类别")
    cognitive_bias: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="识别的认知偏见")

    # 关联洞察
    insight_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="自动生成的 AIInsight.id")

    # LLM 元数据
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True, default="deepseek-reasoner")
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    generation_latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed", comment="pending/running/completed/failed")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_dpm_account_symbol", "account_id", "symbol"),
        Index("idx_dpm_trade", "trade_id", unique=True),
        {"comment": "决策事后剖析报告 V10.3.3"},
    )
