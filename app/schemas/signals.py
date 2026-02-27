"""V10.2-M4: 六维信号融合 Pydantic schema"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DimensionScoreItem(BaseModel):
    name:        str
    score:       float
    weight:      float
    direction:   int    # +1 / 0 / -1
    description: str


class FusedSignalRequest(BaseModel):
    symbol:    str
    regime:    str
    # 各维度原始评分（0-1）；缺省时视为中性 0.5
    technical_score:      Optional[float] = None
    fundamental_score:    Optional[float] = None
    macro_score:          Optional[float] = None
    volume_anomaly_score: Optional[float] = None
    options_score:        Optional[float] = None
    # 情绪原始数据（替代 sentiment_score）
    short_interest_pct:   Optional[float] = None
    retail_sentiment:     Optional[float] = None
    news_sentiment:       Optional[float] = None
    insider_net_bought:   Optional[float] = None


class FusedSignalResponse(BaseModel):
    symbol:              str
    fused_confidence:    float
    base_score:          float
    resonance_bonus:     float
    conflict_penalty:    float
    regime_multiplier:   float
    regime:              str
    aligned_count:       int
    dominant_dimension:  str
    recommendation:      str
    dimensions:          list[DimensionScoreItem]


class SentimentScoreResponse(BaseModel):
    symbol:              str
    score:               float
    direction:           int
    description:         str
    components_used:     int
