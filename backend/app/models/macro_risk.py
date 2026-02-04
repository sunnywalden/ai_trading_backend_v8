"""宏观风险评分模型"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from app.models.db import Base


class MacroRiskScore(Base):
    __tablename__ = "macro_risk_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)

    # 分项评分 (0-100)
    monetary_policy_score = Column(Integer)
    geopolitical_score = Column(Integer)
    sector_bubble_score = Column(Integer)
    economic_cycle_score = Column(Integer)
    sentiment_score = Column(Integer)

    # 综合评分
    overall_score = Column(Integer)
    risk_level = Column(String(16))  # LOW/MEDIUM/HIGH/EXTREME

    # AI分析
    risk_summary = Column(Text)
    key_concerns = Column(Text)  # JSON array
    recommendations = Column(Text)

    # 元数据
    data_sources = Column(Text)  # JSON array
    confidence = Column(Float)


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    indicator_type = Column(String(32), nullable=False)  # MONETARY/ECONOMIC/SENTIMENT

    # 货币政策
    fed_rate = Column(Float)
    m2_growth_rate = Column(Float)
    fed_balance_sheet = Column(Integer)
    inflation_rate = Column(Float)
    dxy_index = Column(Float)

    # 经济周期
    gdp_growth = Column(Float)
    unemployment_rate = Column(Float)
    pmi_index = Column(Float)
    yield_curve_2y10y = Column(Float)
    recession_probability = Column(Float)

    # 市场情绪
    vix_index = Column(Float)
    put_call_ratio = Column(Float)
    fear_greed_index = Column(Integer)


class GeopoliticalEvent(Base):
    __tablename__ = "geopolitical_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_date = Column(DateTime, nullable=False)
    event_type = Column(String(32))  # TRADE_WAR/MILITARY/ELECTION/SANCTION
    category = Column(String(32))
    region = Column(String(64))
    title = Column(String(200)) # Increased length
    description = Column(Text)

    # 影响评估
    severity = Column(String(16))  # LOW/MEDIUM/HIGH/CRITICAL
    affected_sectors = Column(Text)  # JSON array
    market_impact_score = Column(Integer)
    
    # 追加字段映射服务
    affected_regions = Column(Text) # JSON array
    affected_industries = Column(Text) # JSON array

    # 来源
    news_source = Column(String(128))
    news_url = Column(Text) # Changed from String(256) to Text for long URLs
    
    created_at = Column(DateTime, default=func.now())
