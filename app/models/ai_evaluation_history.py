"""
AI 评估历史记录模型

存储 AI 交易决策评估的历史记录，以标的代码为唯一主键，再次评估时覆盖旧记录
"""
from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, JSON, Text, text, Index, UniqueConstraint
from app.models.db import Base


class AIEvaluationHistory(Base):
    __tablename__ = "ai_evaluation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, comment="账户ID")
    
    symbol = Column(String(32), nullable=False, comment="标的代码")
    current_price = Column(DECIMAL(20, 6), nullable=True, comment="评估时的价格")
    
    # AI 决策核心字段
    direction = Column(String(16), nullable=True, comment="方向: LONG/SHORT/NEUTRAL")
    confidence = Column(Integer, nullable=True, comment="置信度 0-100")
    action = Column(String(16), nullable=True, comment="操作: BUY/SELL/HOLD/AVOID")
    
    entry_price = Column(DECIMAL(20, 6), nullable=True, comment="建议入场价")
    stop_loss = Column(DECIMAL(20, 6), nullable=True, comment="止损价")
    take_profit = Column(DECIMAL(20, 6), nullable=True, comment="止盈价")
    position_pct = Column(DECIMAL(10, 4), nullable=True, comment="建议仓位比例")
    
    risk_level = Column(String(16), nullable=True, comment="风险等级: LOW/MEDIUM/HIGH")
    reasoning = Column(Text, nullable=True, comment="决策理由")
    key_factors = Column(JSON, nullable=True, comment="关键因素列表")
    
    # 华尔街增强字段
    risk_reward_ratio = Column(String(16), nullable=True, comment="风险收益比")
    scenarios = Column(JSON, nullable=True, comment="情景分析")
    catalysts = Column(JSON, nullable=True, comment="催化剂")
    holding_period = Column(String(64), nullable=True, comment="持有周期")
    
    # 多维评分
    dimensions = Column(JSON, nullable=True, comment="技术面/基本面/K线分析详情")
    
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"), comment="创建时间")
    updated_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"), comment="更新时间")

    __table_args__ = (
        UniqueConstraint("account_id", "symbol", name="uk_account_symbol"),
        Index("idx_eval_symbol", "symbol"),
        Index("idx_eval_created", "created_at"),
    )
