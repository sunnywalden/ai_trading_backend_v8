"""持仓评估相关的数据传输对象"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ============ 简化版响应模型 ============

class PositionsAssessmentResponse(BaseModel):
    """持仓评估响应（扩展版）"""
    positions: List[Dict[str, Any]]
    summary: Dict[str, Any]
    portfolio_analysis: Optional[Dict[str, Any]] = None
    ai_recommendations: Optional[List[Dict[str, Any]]] = None


class TechnicalAnalysisResponse(BaseModel):
    """技术分析响应（简化版）"""
    symbol: str
    timeframe: str
    trend_direction: Optional[str] = None
    trend_strength: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    support: Optional[List[float]] = None
    resistance: Optional[List[float]] = None
    volume_ratio: Optional[float] = None
    overall_score: float
    ai_summary: Optional[str] = Field(None, description="AI生成的技术面分析摘要")
    timestamp: datetime


class FundamentalAnalysisResponse(BaseModel):
    """基本面分析响应（简化版）"""
    symbol: str
    valuation: Dict[str, Any]
    profitability: Dict[str, Any]
    growth: Dict[str, Any]
    health: Dict[str, Any]
    overall_score: float
    ai_summary: Optional[str] = Field(None, description="AI生成的基本面分析摘要")
    timestamp: datetime


# ============ 详细版DTO（未来扩展用） ============

class TechnicalAnalysisDTO(BaseModel):
    """技术分析DTO"""
    trend_direction: str = Field(..., description="趋势方向: BULLISH/BEARISH/SIDEWAYS")
    trend_strength: int = Field(..., ge=0, le=100, description="趋势强度")
    description: str
    timestamp: datetime = Field(default_factory=datetime.now, description="分析时间戳")
    volume_ratio: Optional[float] = Field(None, description="成交量与20日均量的比值")

    class RSI(BaseModel):
        value: float
        status: str  # OVERSOLD/NEUTRAL/OVERBOUGHT
        signal: str  # BUY/HOLD/SELL

    class MACD(BaseModel):
        value: float
        signal_line: float
        histogram: float
        status: str

    class BollingerBands(BaseModel):
        upper: float
        middle: float
        lower: float
        current_price: float
        position: str
        width_percentile: int

    rsi: RSI
    macd: MACD
    bollinger_bands: BollingerBands
    support_levels: List[float]
    resistance_levels: List[float]
    ai_summary: str


class FundamentalAnalysisDTO(BaseModel):
    """基本面分析DTO"""
    class Valuation(BaseModel):
        pe_ratio: float
        pe_percentile: int
        sector_avg_pe: float
        peg_ratio: float
        pb_ratio: float
        ps_ratio: float
        valuation_grade: str
        comment: str

    class Profitability(BaseModel):
        roe: float
        roa: float
        gross_margin: float
        operating_margin: float
        net_margin: float
        profitability_grade: str

    class Growth(BaseModel):
        revenue_growth_yoy: float
        revenue_growth_qoq: float
        eps_growth_yoy: float
        earnings_surprise_last_4q: List[float]
        growth_grade: str

    class FinancialHealth(BaseModel):
        debt_to_equity: float
        current_ratio: float
        quick_ratio: float
        free_cash_flow: int
        cash_and_equivalents: int
        health_grade: str

    class AnalystRatings(BaseModel):
        consensus: str
        strong_buy: int
        buy: int
        hold: int
        sell: int
        strong_sell: int
        avg_price_target: float
        price_target_range: List[float]

    valuation: Valuation
    profitability: Profitability
    growth: Growth
    financial_health: FinancialHealth
    analyst_ratings: Optional[AnalystRatings]
    ai_summary: str


class PositionScoreDTO(BaseModel):
    """持仓评分DTO"""
    symbol: str
    overall_score: int = Field(..., ge=0, le=100)
    technical_score: int = Field(..., ge=0, le=100)
    fundamental_score: int = Field(..., ge=0, le=100)
    sentiment_score: int = Field(..., ge=0, le=100)


class PositionRecommendationDTO(BaseModel):
    """持仓建议DTO"""
    action: str = Field(..., description="BUY/HOLD/REDUCE/SELL")
    confidence: float = Field(..., ge=0, le=1)
    reason: str
    target_weight: float
    stop_loss: Optional[float]
    take_profit: Optional[float]

class TrendSnapshotDTO(BaseModel):
    """日线趋势快照"""
    trend_direction: str
    trend_strength: int
    trend_description: str
    bollinger_position: str
    volume_ratio: Optional[float]
    support_levels: List[float]
    resistance_levels: List[float]
    ai_summary: Optional[str]
    rsi_value: Optional[float]
    rsi_status: Optional[str]
    macd_status: Optional[str]
    timestamp: Optional[datetime]


class RiskAlertDTO(BaseModel):
    """风险预警DTO"""
    level: str = Field(..., description="LOW/MEDIUM/HIGH/CRITICAL")
    type: str
    message: str


class PositionAssessmentDTO(BaseModel):
    """单个持仓评估DTO"""
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    unrealized_pnl: float
    pnl_pct: float
    weight: float

    trend_snapshot: Optional[TrendSnapshotDTO]

    scores: PositionScoreDTO
    recommendation: PositionRecommendationDTO
    risk_alerts: List[RiskAlertDTO]


class PortfolioSummaryDTO(BaseModel):
    """组合总结DTO"""
    avg_technical_score: int
    avg_fundamental_score: int
    diversification_score: int
    concentration_risk: str
    sector_exposure: Dict[str, float]
