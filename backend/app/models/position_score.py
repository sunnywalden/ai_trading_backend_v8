"""持仓评分数据模型"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from app.models.db import Base


class PositionScore(Base):
    __tablename__ = "position_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    sector = Column(String(64))
    industry = Column(String(128))

    # 综合评分
    overall_score = Column(Integer)
    technical_score = Column(Integer)
    fundamental_score = Column(Integer)
    sentiment_score = Column(Integer)

    # 技术面详情
    trend_direction = Column(String(16))  # BULLISH/BEARISH/SIDEWAYS
    trend_strength = Column(Integer)
    rsi_value = Column(Float)
    rsi_status = Column(String(16))  # OVERSOLD/NEUTRAL/OVERBOUGHT
    macd_signal = Column(String(32))

    # 基本面详情
    pe_ratio = Column(Float)
    peg_ratio = Column(Float)
    beta = Column(Float)
    roe = Column(Float)
    revenue_growth_yoy = Column(Float)
    valuation_grade = Column(String(4))  # A/B/C/D/F
    profitability_grade = Column(String(8))

    # AI总结
    technical_summary = Column(Text)
    fundamental_summary = Column(Text)
    recommendation = Column(String(16))  # BUY/HOLD/REDUCE/SELL
