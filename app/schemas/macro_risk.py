"""宏观风险分析相关的数据传输对象"""
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class MonetaryPolicyDTO(BaseModel):
    """货币政策DTO"""
    score: int = Field(..., ge=0, le=100)
    level: str = Field(..., description="LOW/MEDIUM/HIGH")
    status: str
    
    class KeyIndicators(BaseModel):
        fed_rate: float
        next_meeting: str
        rate_cut_probability: float
        inflation_cpi: float
        inflation_target: float
    
    key_indicators: KeyIndicators
    
    class Impact(BaseModel):
        positive_sectors: List[str]
        negative_sectors: List[str]
    
    impact: Impact


class GeopoliticalDTO(BaseModel):
    """地缘政治DTO"""
    score: int = Field(..., ge=0, le=100)
    level: str
    
    class HotSpot(BaseModel):
        event: str
        severity: str
        probability: float
        impact: str
    
    hot_spots: List[HotSpot]
    safe_haven_recommendation: str


class SectorBubbleDTO(BaseModel):
    """行业泡沫DTO"""
    score: int = Field(..., ge=0, le=100)
    level: str
    
    class Bubble(BaseModel):
        sector: str
        bubble_probability: float
        
        class Indicators(BaseModel):
            avg_pe: float
            historical_percentile: int
            retail_ownership: float
            margin_debt: str
        
        indicators: Indicators
        warning: str
    
    bubbles: List[Bubble]


class EconomicCycleDTO(BaseModel):
    """经济周期DTO"""
    score: int = Field(..., ge=0, le=100)
    level: str
    stage: str
    recession_probability: float
    time_to_recession: str
    
    class LeadingIndicators(BaseModel):
        pmi: float
        yield_curve: float
        unemployment_trend: str
        consumer_confidence: float
    
    leading_indicators: LeadingIndicators
    defensive_strategy: str


class MarketSentimentDTO(BaseModel):
    """市场情绪DTO"""
    score: int = Field(..., ge=0, le=100)
    level: str
    status: str
    
    class Indicators(BaseModel):
        vix: float
        put_call_ratio: float
        fear_greed_index: int
        aaii_bullish: float
        aaii_bearish: float
    
    indicators: Indicators
    warning: str


class OverallRiskDTO(BaseModel):
    """综合风险DTO"""
    score: int = Field(..., ge=0, le=100)
    level: str = Field(..., description="LOW/MEDIUM/HIGH/EXTREME")
    trend: str = Field(..., description="INCREASING/STABLE/DECREASING")
    summary: str


class RiskBreakdownDTO(BaseModel):
    """风险分解DTO"""
    monetary_policy: MonetaryPolicyDTO
    geopolitical: GeopoliticalDTO
    sector_bubble: SectorBubbleDTO
    economic_cycle: EconomicCycleDTO
    market_sentiment: MarketSentimentDTO


class KeyEventDTO(BaseModel):
    """关键事件DTO"""
    date: str
    event: str
    importance: str = Field(..., description="LOW/MEDIUM/HIGH/CRITICAL")


class MacroRiskOverviewResponse(BaseModel):
    """宏观风险概览响应"""
    timestamp: datetime
    overall_risk: OverallRiskDTO
    risk_breakdown: RiskBreakdownDTO
    ai_recommendations: List[str]
    next_key_events: List[KeyEventDTO]
